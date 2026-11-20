"""Tests for the Claude pipeline using a fake Claude (no API calls).

Run from the project folder:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_claude import FakeClaude  # noqa: E402

from recon_claude.config import ReconConfig  # noqa: E402
from recon_claude.control import CHECK_CASH_BANK, CHECK_HOLDINGS, CHECK_PRICE, run_control  # noqa: E402
from recon_claude.errors import ReportError, SourceFormatError, SourceMissingError  # noqa: E402
from recon_claude.extraction import extract_all  # noqa: E402
from recon_claude.models import BREAK, MATCHED, REVIEW, ControlItem  # noqa: E402
from recon_claude.pipeline import discover_sources, run_reconciliation  # noqa: E402
from recon_claude.reconcile import verify  # noqa: E402
from recon_claude.reports import ungrounded_numbers  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT.parent / "sample-data"
CONFIG = ReconConfig.from_file(ROOT / "config.json")

EXPECTED_BREAKS = {
    (CHECK_CASH_BANK, date(2026, 10, 7), "ACC1001"),
    (CHECK_CASH_BANK, date(2026, 10, 8), "ACC1001"),
    (CHECK_HOLDINGS, date(2026, 10, 15), "CUST2001/ZZ0000000002"),
    (CHECK_PRICE, date(2026, 10, 23), "ZZ0000000003"),
}


def prepared_fake() -> tuple[FakeClaude, object]:
    fake = FakeClaude(CONFIG.tolerances)
    files, _ = discover_sources(CONFIG, SAMPLE)
    data, _ = extract_all(fake, files, CONFIG)
    fake.reference = data
    return fake, data


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name)
        cls.fake, _ = prepared_fake()
        cls.result = run_reconciliation(CONFIG, SAMPLE, cls.out, llm=cls.fake)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_only_planted_breaks_are_open(self) -> None:
        found = {(i.check, i.as_of, i.subject) for i in self.result.open_items}
        self.assertEqual(found, EXPECTED_BREAKS)
        self.assertTrue(all(i.status == BREAK for i in self.result.open_items))

    def test_cash_break_is_1250(self) -> None:
        diffs = {i.as_of: i.difference.copy_abs() for i in self.result.open_items if i.check == CHECK_CASH_BANK}
        self.assertEqual(diffs, {date(2026, 10, 7): 1250, date(2026, 10, 8): 1250})

    def test_break_queue_has_claude_annotations(self) -> None:
        with (self.out / "break_queue.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["priority"] == "high" and r["suggested_action"] for r in rows))
        self.assertTrue((self.out / "review_report.md").exists())

    def test_investor_statement_uses_only_reconciled_figures(self) -> None:
        self.assertEqual(self.result.statement_date, "2026-10-30")
        markdown = (self.out / "investor_statement_FUND01_2026-10-30.md").read_text(encoding="utf-8")
        self.assertTrue((self.out / "investor_statement_FUND01_2026-10-30.html").exists())
        for dated in ("7 October 2026", "8 October 2026"):  # cash days with open breaks
            self.assertNotIn(f"| {dated} |", markdown)
        self.assertIn("| 9 October 2026 |", markdown)
        self.assertIn("| 30 October 2026 |", markdown)
        self.assertNotIn("1250", markdown)

    def test_summary(self) -> None:
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "completed_with_breaks")
        self.assertEqual(summary["open_items"], 4)
        self.assertEqual(len(summary["input_files_sha256"]), 7)
        self.assertEqual(summary["verification"], {"agreed": summary["comparisons"]})


class ExtractionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files, _ = discover_sources(CONFIG, SAMPLE)

    def test_bad_first_attempt_is_retried(self) -> None:
        fake = FakeClaude(CONFIG.tolerances)
        fake.extract_hook = lambda source, attempt, rows: rows[:-1] if attempt == 1 and source == "custody" else rows
        extract_all(fake, self.files, CONFIG)
        self.assertTrue(any(n == 2 for n in fake.extract_calls.values()))

    def test_persistent_dropped_row_fails_the_run(self) -> None:
        fake = FakeClaude(CONFIG.tolerances)
        fake.extract_hook = lambda source, attempt, rows: rows[:-1] if source == "custody" else rows
        with self.assertRaises(SourceFormatError):
            extract_all(fake, self.files, CONFIG)

    def test_altered_amount_is_rejected(self) -> None:
        def corrupt(source, attempt, rows):
            if source == "admin_cash":
                rows = [dict(r) for r in rows]
                rows[0]["ledger_balance"] = "123456.78"
            return rows

        fake = FakeClaude(CONFIG.tolerances)
        fake.extract_hook = corrupt
        with self.assertRaises(SourceFormatError):
            extract_all(fake, self.files, CONFIG)

    def test_missing_feed_raises(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(SourceMissingError):
                run_reconciliation(CONFIG, Path(empty), Path(empty) / "out", llm=FakeClaude())


class VerificationTests(unittest.TestCase):
    D = date(2026, 10, 1)

    def control(self, status=MATCHED, left="10", right="10", diff="0") -> ControlItem:
        return ControlItem("c", self.D, "A", "l", Decimal(left), "r", Decimal(right), Decimal(diff), status)

    def row(self, status="MATCHED", left="10", right="10", diff="0", subject="A") -> dict:
        return {"check": "c", "as_of_date": "2026-10-01", "subject": subject, "left_label": "l", "left": left,
                "right_label": "r", "right": right, "difference": diff, "status": status, "note": ""}

    def test_agreement(self) -> None:
        [item] = verify([self.row()], [self.control()])
        self.assertEqual((item.status, item.verification), (MATCHED, "agreed"))

    def test_status_disagreement_goes_to_review(self) -> None:
        [item] = verify([self.row(status="BREAK")], [self.control()])
        self.assertEqual((item.status, item.verification), (REVIEW, "status_disagreement"))

    def test_claude_calling_a_break_matched_goes_to_review(self) -> None:
        [item] = verify([self.row()], [self.control(BREAK, "10", "5", "5")])
        self.assertEqual(item.status, REVIEW)

    def test_omitted_comparison_goes_to_review(self) -> None:
        [item] = verify([], [self.control()])
        self.assertEqual((item.status, item.verification), (REVIEW, "missing_from_claude"))

    def test_invented_comparison_goes_to_review(self) -> None:
        items = verify([self.row(), self.row(subject="B")], [self.control()])
        self.assertEqual({i.subject: i.verification for i in items}, {"A": "agreed", "B": "not_in_control"})

    def test_duplicate_goes_to_review(self) -> None:
        [item] = verify([self.row(), self.row()], [self.control()])
        self.assertEqual(item.verification, "duplicate_from_claude")

    def test_wrong_figures_with_right_status_use_control_figures(self) -> None:
        [item] = verify([self.row(diff="0.001")], [self.control()])
        self.assertEqual((item.status, item.verification, item.difference), (MATCHED, "values_differ", Decimal("0")))


class ReconciliationFaultTests(unittest.TestCase):
    def test_claude_missing_a_break_is_sent_to_review(self) -> None:
        fake, _ = prepared_fake()

        def hide_break(check, rows):
            for r in rows:
                if r["status"] == "BREAK":
                    r.update(status="MATCHED", difference="0")
            return rows

        fake.reconcile_hook = hide_break
        with tempfile.TemporaryDirectory() as out:
            result = run_reconciliation(CONFIG, SAMPLE, Path(out), llm=fake)
        review = [i for i in result.open_items if i.status == REVIEW]
        self.assertEqual(len(review), 4)  # nothing a model slip hides can pass silently

    def test_claude_dropping_comparisons_is_sent_to_review(self) -> None:
        fake, _ = prepared_fake()
        fake.reconcile_hook = lambda check, rows: rows[1:] if check == CHECK_HOLDINGS else rows
        with tempfile.TemporaryDirectory() as out:
            result = run_reconciliation(CONFIG, SAMPLE, Path(out), llm=fake)
        self.assertTrue(any(i.verification == "missing_from_claude" for i in result.open_items))


class StatementGroundingTests(unittest.TestCase):
    def test_ungrounded_number_helper(self) -> None:
        facts = {"total": "1234567.50"}
        self.assertEqual(ungrounded_numbers(["Total 1,234,567.50 across 3 days"], facts), [])
        self.assertEqual(ungrounded_numbers(["Total 999,999.99"], facts), ["999999.99"])

    def test_invented_number_is_retried_then_rejected(self) -> None:
        fake, _ = prepared_fake()
        fake.statement_hook = lambda attempt, text: {**text, "introduction": "Growth was 7.35 percent."}
        with tempfile.TemporaryDirectory() as out:
            with self.assertRaises(ReportError):
                run_reconciliation(CONFIG, SAMPLE, Path(out), llm=fake)
            summary = json.loads((Path(out) / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "completed_report_failed")
            self.assertTrue((Path(out) / "break_queue.csv").exists())  # exceptions are never lost
        self.assertEqual(fake.calls.count("investor_statement"), 2)

    def test_invented_number_corrected_on_retry(self) -> None:
        fake, _ = prepared_fake()
        fake.statement_hook = lambda attempt, text: (
            {**text, "introduction": "Growth was 7.35 percent."} if attempt == 1 else text)
        with tempfile.TemporaryDirectory() as out:
            result = run_reconciliation(CONFIG, SAMPLE, Path(out), llm=fake)
        self.assertEqual(result.statement_date, "2026-10-30")


if __name__ == "__main__":
    unittest.main()
