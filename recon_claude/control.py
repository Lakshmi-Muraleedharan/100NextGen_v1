"""Deterministic control for Claude's reconciliation.

Claude performs the reconciliation. This module independently recomputes every
comparison with plain Decimal arithmetic (ported from the fund_reconciliation
prototype) so that Claude's answer can be verified. It never produces output
for users; it only supplies the expected result that reconcile.py compares
Claude's result against.

`CHECKS` is the single definition of the seven checks: both the control and
the prompt sent to Claude are built from the same labels and subject formats,
so the two result sets can be keyed identically.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Iterator, Optional

from .config import Tolerances
from .models import BREAK, MATCHED, MISSING, ControlItem, SourceData

CHECK_CASH_BANK = "cash_ledger_vs_bank"
CHECK_CASH_MOVEMENT = "cash_movement_vs_prime_broker"
CHECK_HOLDINGS = "holdings_admin_vs_custody"
CHECK_MARKET_VALUE = "market_value_recalculation"
CHECK_PRICE = "price_admin_vs_vendor"
CHECK_EMAIL = "email_closing_vs_ledger"
CHECK_STATEMENT = "statement_integrity"

CASH_CHECKS = {CHECK_CASH_BANK, CHECK_CASH_MOVEMENT, CHECK_EMAIL, CHECK_STATEMENT}
HOLDING_CHECKS = {CHECK_HOLDINGS, CHECK_MARKET_VALUE, CHECK_PRICE}

BPS = Decimal("10000")
CENT = Decimal("0.01")


def _outer_join(left: dict, right: dict) -> Iterator[tuple[Any, Optional[Any], Optional[Any]]]:
    for key in sorted(set(left) | set(right)):
        yield key, left.get(key), right.get(key)


def _item(
    check: str, as_of, subject: str, left_label: str, left: Optional[Decimal],
    right_label: str, right: Optional[Decimal], tolerance: Decimal,
) -> ControlItem:
    """Compare two values by absolute difference."""
    if left is None or right is None:
        return ControlItem(check, as_of, subject, left_label, left, right_label, right, None, MISSING)
    difference = left - right
    status = MATCHED if abs(difference) <= tolerance else BREAK
    return ControlItem(check, as_of, subject, left_label, left, right_label, right, difference, status)


def _compare_maps(
    check: str, left: dict, right: dict, tolerance: Decimal, left_label: str, right_label: str
) -> list[ControlItem]:
    """Compare two keyed maps. Keys are (as_of, *subject parts)."""
    items = []
    for key, left_value, right_value in _outer_join(left, right):
        as_of, *parts = key
        subject = "/".join(str(part) for part in parts)
        items.append(_item(check, as_of, subject, left_label, left_value, right_label, right_value, tolerance))
    return items


def _ledger_moves(data: SourceData) -> dict[tuple, Decimal]:
    by_account: dict[str, list] = defaultdict(list)
    for row in sorted(data.admin_cash, key=lambda r: (r.account_id, r.as_of)):
        by_account[row.account_id].append(row)
    moves: dict[tuple, Decimal] = {}
    for account, rows in by_account.items():
        for previous, current in zip(rows, rows[1:]):
            moves[(current.as_of, account)] = current.amount - previous.amount
    return moves


def run_control(data: SourceData, tol: Tolerances) -> list[ControlItem]:
    """Every comparison the seven checks make, with the control's verdict."""
    items: list[ControlItem] = []

    ledger = {(r.as_of, r.account_id): r.amount for r in data.admin_cash}
    bank = {(r.as_of, r.account_id): r.closing for r in data.bank_statements}
    items += _compare_maps(CHECK_CASH_BANK, ledger, bank, tol.cash, "admin_ledger", "bank_closing")

    moves = _ledger_moves(data)
    pb: dict[tuple, Decimal] = defaultdict(Decimal)
    for m in data.prime_broker:
        pb[(m.as_of, m.account_id)] += m.amount
    comparable_pb = {k: v for k, v in pb.items() if k in moves}
    items += _compare_maps(
        CHECK_CASH_MOVEMENT, moves, comparable_pb, tol.cash,
        "admin_ledger_movement", "prime_broker_movement",
    )

    admin_qty = {(h.as_of, h.account_id, h.security_id): h.quantity for h in data.admin_holdings}
    custody_qty = {(c.as_of, c.account_id, c.security_id): c.quantity for c in data.custody}
    items += _compare_maps(
        CHECK_HOLDINGS, admin_qty, custody_qty, tol.holding_quantity, "admin_quantity", "custody_quantity"
    )

    for h in data.admin_holdings:
        items.append(
            _item(
                CHECK_MARKET_VALUE, h.as_of, f"{h.account_id}/{h.security_id}",
                "admin_market_value", h.market_value,
                "quantity_x_price", (h.quantity * h.price).quantize(CENT), tol.market_value,
            )
        )

    admin_price = {(h.as_of, h.security_id): h.price for h in data.admin_holdings}
    vendor_price = {(p.as_of, p.security_id): p.close_price for p in data.vendor_prices}
    for (as_of, security_id), a_price, v_price in _outer_join(admin_price, vendor_price):
        if a_price is None or v_price is None:
            items.append(
                ControlItem(CHECK_PRICE, as_of, security_id, "admin_price", a_price,
                            "vendor_price", v_price, None, MISSING)
            )
            continue
        if v_price <= 0:
            continue  # the prototype skips non-positive vendor prices
        bps = (abs(a_price - v_price) / v_price * BPS).quantize(CENT)
        status = MATCHED if abs(a_price - v_price) / v_price * BPS <= tol.price_bps else BREAK
        items.append(
            ControlItem(CHECK_PRICE, as_of, security_id, "admin_price", a_price,
                        "vendor_price", v_price, bps, status)
        )

    emails = {(e.as_of, e.account_id): e.closing for e in data.email_summaries}
    items += _compare_maps(
        CHECK_EMAIL, {k: v for k, v in ledger.items() if k in emails} , emails,
        tol.email_closing, "admin_ledger", "email_closing",
    )

    for s in data.bank_statements:
        items.append(
            _item(CHECK_STATEMENT, s.as_of, s.account_id, "opening_plus_movements",
                  s.opening + s.movement, "closing", s.closing, tol.cash)
        )
    by_account: dict[str, list] = defaultdict(list)
    for s in sorted(data.bank_statements, key=lambda r: (r.account_id, r.as_of)):
        by_account[s.account_id].append(s)
    for account, rows in by_account.items():
        for previous, current in zip(rows, rows[1:]):
            items.append(
                _item(CHECK_STATEMENT, current.as_of, account, "previous_closing",
                      previous.closing, "opening", current.opening, tol.cash)
            )
    return items


# ---------------------------------------------------------------------------
# Check definitions shared with the Claude prompt
# ---------------------------------------------------------------------------

def check_specs(tol: Tolerances) -> dict[str, dict[str, Any]]:
    """Human-readable definition of each check, used to instruct Claude.

    `datasets` names the input collections the check needs. Labels and subject
    formats are exactly the ones run_control() emits.
    """
    return {
        CHECK_CASH_BANK: {
            "datasets": ["admin_cash", "bank_statements"],
            "rule": (
                "For every (date, account) in either dataset compare the admin ledger balance "
                "(admin_cash.ledger_balance) with the bank statement closing balance "
                "(bank_statements.closing). Join on as_of_date + account_id."
            ),
            "subject": "account_id",
            "labels": [("admin_ledger", "bank_closing")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.cash}",
        },
        CHECK_CASH_MOVEMENT: {
            "datasets": ["admin_cash", "prime_broker"],
            "rule": (
                "For each account, the admin ledger movement on a date is that day's ledger balance "
                "minus the same account's previous ledger balance (the previous row for that account, "
                "which may come from before the window). The prime broker movement is the sum of "
                "prime_broker.amount for that date and account. Compare them for every date that has "
                "an admin ledger movement (a date with a prior balance). Prime broker dates without "
                "an admin movement are not compared. If an admin movement exists but the prime broker "
                "has no rows for that date, the prime broker side is missing."
            ),
            "subject": "account_id",
            "labels": [("admin_ledger_movement", "prime_broker_movement")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.cash}",
        },
        CHECK_HOLDINGS: {
            "datasets": ["admin_holdings", "custody"],
            "rule": (
                "For every (date, account, security) in either dataset compare the admin quantity "
                "with the custodian quantity. Join on as_of_date + account_id + security_id "
                "(custody.account_id is the custodian account)."
            ),
            "subject": "account_id/security_id",
            "labels": [("admin_quantity", "custody_quantity")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.holding_quantity}",
        },
        CHECK_MARKET_VALUE: {
            "datasets": ["admin_holdings"],
            "rule": (
                "For every admin holding row compare its market_value with quantity multiplied by "
                "price, rounded to 2 decimal places (round half to even)."
            ),
            "subject": "account_id/security_id",
            "labels": [("admin_market_value", "quantity_x_price")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.market_value}",
        },
        CHECK_PRICE: {
            "datasets": ["admin_holdings", "vendor_prices"],
            "rule": (
                "For every (date, security) in either dataset compare the admin price "
                "(admin_holdings.price) with the vendor close_price. Join on as_of_date + security_id."
            ),
            "subject": "security_id",
            "labels": [("admin_price", "vendor_price")],
            "difference": (
                "difference in basis points: |admin - vendor| / vendor * 10000, rounded to 2 decimal "
                "places, never negative (empty when a side is missing)"
            ),
            "tolerance": f"{tol.price_bps} basis points (a difference equal to it still matches)",
        },
        CHECK_EMAIL: {
            "datasets": ["admin_cash", "email_summaries"],
            "rule": (
                "For every email summary compare its closing cash with the admin ledger balance for "
                "the same date and account. Only dates that have an email summary are compared; if "
                "the ledger has no balance for that date the left side is missing."
            ),
            "subject": "account_id",
            "labels": [("admin_ledger", "email_closing")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.email_closing}",
        },
        CHECK_STATEMENT: {
            "datasets": ["bank_statements"],
            "rule": (
                "Two comparisons per bank statement. (1) Within each statement: opening + movement "
                "(movement is the statement's net transaction total) versus closing; "
                "left_label=opening_plus_movements, right_label=closing, as_of_date = the statement date. "
                "(2) Continuity: for each account, each statement after the first has its opening "
                "balance compared with the previous statement's closing (previous = the prior statement "
                "for that account, possibly from before the window); left_label=previous_closing, "
                "right_label=opening, as_of_date = the later statement's date."
            ),
            "subject": "account_id",
            "labels": [("opening_plus_movements", "closing"), ("previous_closing", "opening")],
            "difference": "left - right",
            "tolerance": f"absolute, {tol.cash}",
        },
    }
