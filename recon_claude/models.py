"""Typed records shared by extraction, reconciliation and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class CashBalance:
    """Admin system ledger cash balance for one account on one date."""

    as_of: date
    fund_id: str
    account_id: str
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class AdminHolding:
    """Admin system holding of one security in one account on one date."""

    as_of: date
    fund_id: str
    account_id: str
    security_id: str
    quantity: Decimal
    price: Decimal
    market_value: Decimal
    currency: str
    security_name: str = ""


@dataclass(frozen=True)
class CustodyPosition:
    """Custodian position for one security in one account on one date."""

    as_of: date
    account_id: str
    security_id: str
    quantity: Decimal
    currency: str


@dataclass(frozen=True)
class BankStatement:
    """Opening, closing and total movement from one MT940 statement."""

    as_of: date
    account_id: str
    currency: str
    opening: Decimal
    closing: Decimal
    movement: Decimal


@dataclass(frozen=True)
class CashMovement:
    """One cash movement reported by the prime broker."""

    as_of: date
    fund_id: str
    account_id: str
    txn_type: str
    reference: str
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class VendorPrice:
    """Closing price for one security from the pricing vendor."""

    as_of: date
    security_id: str
    currency: str
    close_price: Decimal


@dataclass(frozen=True)
class EmailSummary:
    """Month-end cash summary received by email from the prime broker."""

    as_of: date
    account_id: str
    currency: str
    opening: Decimal
    closing: Decimal


@dataclass
class SourceData:
    """All records extracted for one run, grouped by source."""

    admin_cash: list[CashBalance] = field(default_factory=list)
    admin_holdings: list[AdminHolding] = field(default_factory=list)
    custody: list[CustodyPosition] = field(default_factory=list)
    bank_statements: list[BankStatement] = field(default_factory=list)
    prime_broker: list[CashMovement] = field(default_factory=list)
    vendor_prices: list[VendorPrice] = field(default_factory=list)
    email_summaries: list[EmailSummary] = field(default_factory=list)


# Final status of one comparison after Claude's result is checked against the control.
MATCHED = "MATCHED"
BREAK = "BREAK"
MISSING = "MISSING"
REVIEW = "REVIEW"  # Claude and the control disagree, or a comparison is absent on one side


@dataclass(frozen=True)
class ControlItem:
    """One comparison as computed by the deterministic control."""

    check: str
    as_of: date
    subject: str
    left_label: str
    left: Optional[Decimal]
    right_label: str
    right: Optional[Decimal]
    difference: Optional[Decimal]
    status: str  # MATCHED, BREAK or MISSING

    @property
    def key(self) -> tuple:
        return (self.check, self.as_of, self.subject, self.left_label)


@dataclass(frozen=True)
class ReconItem:
    """One comparison in the final reconciliation result."""

    check: str
    as_of: date
    subject: str
    left_label: str
    left: Optional[Decimal]
    right_label: str
    right: Optional[Decimal]
    difference: Optional[Decimal]
    status: str  # MATCHED, BREAK, MISSING or REVIEW
    claude_status: str  # what Claude concluded ("" if it produced nothing)
    control_status: str  # what the control concluded ("" if it produced nothing)
    verification: str  # agreed | values_differ | status_disagreement | missing_from_claude | not_in_control | duplicate_from_claude
    note: str

    @property
    def key(self) -> tuple:
        return (self.check, self.as_of, self.subject, self.left_label)
