"""End-to-end run: discover -> extract (Claude) -> reconcile (Claude) -> report (Claude).

Outputs (in the output folder):
  break_queue.csv                        items for human review (BREAK / MISSING / REVIEW)
  review_report.md                       Claude's analysis of those items
  investor_statement_<fund>_<date>.md    statement built only from reconciled figures
  investor_statement_<fund>_<date>.html  same statement, formatted
  reconciliation_results.csv             every comparison, for audit
  extracted_records.json                 what Claude extracted from each source file
  summary.json                           run status, counts, token usage, input file hashes

A run fails fast when a feed is missing or its extraction cannot be validated.
The break queue is written before any narrative report is attempted, so a
report failure never loses the exceptions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import anthropic

from .config import ReconConfig
from .credentials import fetch_api_key
from .errors import ReconciliationError, ReportError, SourceMissingError
from .extraction import extract_all
from .llm import ClaudeClient
from .models import MATCHED, REVIEW, ReconItem
from .reconcile import reconcile
from .reports import Annotation, generate_investor_statement, generate_review_report, open_items

logger = logging.getLogger(__name__)

RESULT_COLUMNS = [
    "check", "as_of_date", "subject", "left_label", "left", "right_label", "right",
    "difference", "status", "claude_status", "control_status", "verification", "note",
]
QUEUE_COLUMNS = RESULT_COLUMNS + ["priority", "likely_cause", "suggested_action"]


@dataclass
class RunResult:
    fund_id: str
    items: list[ReconItem]
    output_dir: Path
    statement_date: Optional[str] = None
    outputs: dict[str, str] = field(default_factory=dict)
    report_error: Optional[str] = None

    @property
    def open_items(self) -> list[ReconItem]:
        return open_items(self.items)

    @property
    def matched(self) -> int:
        return sum(1 for i in self.items if i.status == MATCHED)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_sources(config: ReconConfig, input_dir: Path) -> tuple[dict[str, list[Path]], dict[str, str]]:
    """Find and hash every source file. Byte-identical duplicates are skipped."""
    logger.info("Discovering source files in %s", input_dir)
    files: dict[str, list[Path]] = {}
    manifest: dict[str, str] = {}
    seen: dict[str, str] = {}
    for source_name, pattern in asdict(config.sources).items():
        matches = sorted(input_dir.glob(pattern))
        if not matches:
            raise SourceMissingError(f"no file matches '{pattern}' for source '{source_name}' in {input_dir}")
        accepted = []
        for path in matches:
            digest = _sha256(path)
            if digest in seen:
                logger.warning("Duplicate file skipped: %s matches %s", path.name, seen[digest])
                continue
            seen[digest] = path.name
            manifest[path.relative_to(input_dir).as_posix()] = digest
            accepted.append(path)
        files[source_name] = accepted
    return files, manifest


def _text(value: Optional[Decimal]) -> str:
    return "" if value is None else str(value)


def _row(item: ReconItem) -> dict[str, str]:
    return {
        "check": item.check, "as_of_date": item.as_of.isoformat(), "subject": item.subject,
        "left_label": item.left_label, "left": _text(item.left),
        "right_label": item.right_label, "right": _text(item.right),
        "difference": _text(item.difference), "status": item.status,
        "claude_status": item.claude_status, "control_status": item.control_status,
        "verification": item.verification, "note": item.note,
    }


def write_results(items: list[ReconItem], path: Path) -> None:
    ordered = sorted(items, key=lambda i: (i.check, i.as_of, i.subject, i.left_label))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(_row(i) for i in ordered)


def write_break_queue(
    queue: list[ReconItem], annotations: dict[int, Annotation], path: Path
) -> None:
    """`annotations` is keyed by 1-based position in `queue` (empty before Claude's analysis)."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS)
        writer.writeheader()
        for n, item in enumerate(queue, start=1):
            a = annotations.get(n)
            writer.writerow({**_row(item), "priority": a.priority if a else "",
                             "likely_cause": a.likely_cause if a else "",
                             "suggested_action": a.suggested_action if a else ""})


def write_summary(
    config: ReconConfig, result: RunResult, usage: dict, manifest: dict[str, str], status: str, path: Path,
    model: str,
) -> None:
    by_check: dict[str, Counter] = {}
    for item in result.items:
        by_check.setdefault(item.check, Counter())[item.status] += 1
    verification = Counter(i.verification for i in result.items)
    summary = {
        "fund_id": config.fund_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "status": status,
        "comparisons": len(result.items),
        "matched": result.matched,
        "open_items": len(result.open_items),
        "checks": {c: dict(counts) for c, counts in sorted(by_check.items())},
        "verification": dict(verification),
        "investor_statement_date": result.statement_date,
        "outputs": result.outputs,
        "report_error": result.report_error,
        "claude_usage": usage,
        "input_files_sha256": manifest,
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_reconciliation(
    config: ReconConfig, input_dir: Path, output_dir: Path, llm: Optional[ClaudeClient] = None
) -> RunResult:
    """Run the whole pipeline. `llm` can be injected (tests); by default it calls the API."""
    if llm is None:
        client = None
        if config.gateway:  # key comes from Azure Key Vault, calls go through the gateway
            client = anthropic.Anthropic(
                api_key=fetch_api_key(config.gateway.vault_url, config.gateway.secret_name),
                base_url=config.gateway.base_url,
            )
        llm = ClaudeClient(config.model, config.effort, client=client)
    logger.info("Starting reconciliation for fund %s with %s", config.fund_id, llm.model)

    files, manifest = discover_sources(config, input_dir)
    data, raw = extract_all(llm, files, config)
    items = reconcile(llm, data, config)

    output_dir.mkdir(parents=True, exist_ok=True)
    result = RunResult(config.fund_id, items, output_dir)
    (output_dir / "extracted_records.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    write_results(items, output_dir / "reconciliation_results.csv")
    queue = result.open_items
    write_break_queue(queue, {}, output_dir / "break_queue.csv")  # safe copy before narrative reports
    result.outputs.update({
        "break_queue": "break_queue.csv",
        "all_results": "reconciliation_results.csv",
        "extracted_records": "extracted_records.json",
    })
    status = "completed_with_breaks" if queue else "completed_no_breaks"
    summary_path = output_dir / "summary.json"
    write_summary(config, result, llm.usage, manifest, status, summary_path, llm.model)

    try:
        annotations, review_md = generate_review_report(llm, config.fund_id, items)
        write_break_queue(queue, annotations, output_dir / "break_queue.csv")
        (output_dir / "review_report.md").write_text(review_md, encoding="utf-8")
        result.outputs["review_report"] = "review_report.md"

        statement = generate_investor_statement(llm, config.fund_id, data, items)
        if statement:
            facts, markdown, html_text = statement
            stem = f"investor_statement_{config.fund_id}_{facts['statement_date']}"
            (output_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
            (output_dir / f"{stem}.html").write_text(html_text, encoding="utf-8")
            result.statement_date = facts["statement_date"]
            result.outputs["investor_statement_md"] = f"{stem}.md"
            result.outputs["investor_statement_html"] = f"{stem}.html"
    except ReconciliationError as exc:
        # Core results are already on disk; record the failure and let the CLI report it.
        result.report_error = str(exc)
        status = "completed_report_failed"
        logger.error("Report generation failed: %s", exc)
    finally:
        write_summary(config, result, llm.usage, manifest, status, summary_path, llm.model)

    logger.info(
        "Done: %d comparison(s), %d matched, %d open item(s) for review (%d REVIEW), %d Claude call(s)",
        len(items), result.matched, len(queue),
        sum(1 for i in queue if i.status == REVIEW), llm.usage["calls"],
    )
    if result.report_error:
        raise ReportError(result.report_error)
    return result
