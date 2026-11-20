"""A stand-in for ClaudeClient used by the tests (no network, no API key).

It behaves like a *correct* Claude: extraction is done with plain csv/regex
parsing, reconciliation answers come from the deterministic control, and the
reports are canned text that quotes only numbers from the facts it receives.
Tests inject faults through the hooks to prove the guards catch them.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Callable, Optional

from recon_claude.control import run_control
from recon_claude.extraction import SPECS


def _mt_amount(sign: str, digits: str) -> str:
    value = digits.replace(",", ".")
    return value if sign == "C" else f"-{value}"


def extract_chunk(source: str, chunk: str) -> list[dict]:
    spec = SPECS[source]
    if spec.kind == "csv":
        return [{k: row[k] for k in spec.fields} for row in csv.DictReader(io.StringIO(chunk))]
    if spec.kind == "mt940":
        records = []
        for block in ["{1:" + b for b in chunk.split("{1:")[1:]]:
            account = re.search(r":25:(?:[^/\n]*/)?(\S+)", block).group(1)
            o_sign, _, currency, o_amt = re.search(r":60F:([CD])(\d{6})([A-Z]{3})(\d+,\d{2})", block).groups()
            c_sign, c_date, _, c_amt = re.search(r":62F:([CD])(\d{6})([A-Z]{3})(\d+,\d{2})", block).groups()
            records.append({
                "as_of_date": datetime.strptime(c_date, "%y%m%d").date().isoformat(),
                "account_id": account, "currency": currency,
                "opening_balance": _mt_amount(o_sign, o_amt),
                "closing_balance": _mt_amount(c_sign, c_amt),
                "transaction_amounts": [
                    _mt_amount(s, a) for s, a in re.findall(r":61:\d{6}(?:\d{4})?([CD])(\d+,\d{2})", block)
                ],
            })
        return records
    opening = re.search(r"Opening cash \((\d{1,2} \w{3} \d{4})\):\s+(-?[\d.]+) (\w{3})", chunk)
    closing = re.search(r"Closing cash \((\d{1,2} \w{3} \d{4})\):\s+(-?[\d.]+) (\w{3})", chunk)
    account = re.search(r"account (\w+)", chunk)
    return [{
        "as_of_date": datetime.strptime(closing.group(1), "%d %b %Y").date().isoformat(),
        "account_id": account.group(1), "currency": closing.group(3),
        "opening_cash": opening.group(2), "closing_cash": closing.group(2),
    }]


class FakeClaude:
    model = "fake-claude"

    def __init__(self, tolerances=None) -> None:
        self.tolerances = tolerances
        self.reference = None  # SourceData; set once extraction has run
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        self.extract_hook: Optional[Callable[[str, int, list[dict]], list[dict]]] = None
        self.reconcile_hook: Optional[Callable[[str, list[dict]], list[dict]]] = None
        self.statement_hook: Optional[Callable[[int, dict], dict]] = None
        self.extract_calls: dict[str, int] = {}
        self.calls: list[str] = []

    def structured(self, *, system: str, user: str, schema: dict, meta: Optional[dict] = None) -> dict:
        meta = meta or {}
        self.usage["calls"] += 1
        self.calls.append(meta["task"])
        return getattr(self, "_" + meta["task"])(meta)

    # -- extraction ---------------------------------------------------------
    def _extract(self, meta: dict) -> dict:
        source = meta["source"]
        records = extract_chunk(source, meta["chunk"])
        attempt = self.extract_calls[meta["label"]] = self.extract_calls.get(meta["label"], 0) + 1
        if self.extract_hook:
            records = self.extract_hook(source, attempt, records)
        return {"records": records}

    # -- reconciliation -----------------------------------------------------
    def _reconcile(self, meta: dict) -> dict:
        rows = []
        for item in run_control(self.reference, self.tolerances):
            if item.check != meta["check"] or not (meta["start"] <= item.as_of.isoformat() <= meta["end"]):
                continue
            rows.append({
                "as_of_date": item.as_of.isoformat(), "subject": item.subject,
                "left_label": item.left_label, "left": "" if item.left is None else str(item.left),
                "right_label": item.right_label, "right": "" if item.right is None else str(item.right),
                "difference": "" if item.difference is None else str(item.difference),
                "status": item.status, "note": "" if item.status == "MATCHED" else "difference noted",
            })
        if self.reconcile_hook:
            rows = self.reconcile_hook(meta["check"], rows)
        return {"comparisons": rows}

    # -- reports ------------------------------------------------------------
    def _review_report(self, meta: dict) -> dict:
        return {
            "summary": f"{len(meta['items'])} item(s) need review.",
            "patterns": ["Items on the same date may share a cause."] if meta["items"] else [],
            "items": [
                {"ref": n, "priority": "high", "likely_cause": "Cannot tell from the data.",
                 "suggested_action": "Check the source records."}
                for n, _ in enumerate(meta["items"], start=1)
            ],
        }

    def _investor_statement(self, meta: dict) -> dict:
        facts = meta["facts"]
        attempt = int(meta["label"].rsplit("#", 1)[1])
        text = {
            "title": f"Investor Statement - {facts['fund_id']}",
            "introduction": f"This statement covers {facts['fund_id']} to {facts['statement_date']}.",
            "position_commentary": f"Total reconciled value was {facts['total_value']} {facts['currency']}; see the table below.",
            "activity_commentary": f"Net subscriptions and redemptions were {facts['net_subscriptions_redemptions']}.",
            "verification_note": (
                f"{facts['verification']['business_days_fully_verified']} of "
                f"{facts['verification']['business_days_in_period']} business days are fully verified."),
            "disclosures": "The total is cash plus securities and is not net asset value.",
        }
        if self.statement_hook:
            text = self.statement_hook(attempt, text)
        return text
