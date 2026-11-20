"""Load and validate the reconciliation configuration file."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from .errors import ConfigError

logger = logging.getLogger(__name__)

REQUIRED_MODEL = "claude-sonnet-5-5--VNGC"


@dataclass(frozen=True)
class Tolerances:
    """Maximum allowed differences. A difference equal to the tolerance still matches."""

    cash: Decimal
    holding_quantity: Decimal
    market_value: Decimal
    price_bps: Decimal
    email_closing: Decimal


@dataclass(frozen=True)
class SourcePatterns:
    """Glob patterns, relative to the input folder, that locate each source feed."""

    admin_cash: str
    admin_holdings: str
    custody: str
    bank_mt940: str
    prime_broker: str
    vendor_prices: str
    email_summary: str


@dataclass(frozen=True)
class Gateway:
    """LLM gateway and the Key Vault secret that holds its API key."""

    base_url: str
    vault_url: str
    secret_name: str


@dataclass(frozen=True)
class ReconConfig:
    """Everything a reconciliation run needs to know before it starts."""

    fund_id: str
    model: str
    effort: str
    max_workers: int
    csv_rows_per_call: int
    mt940_statements_per_call: int
    dates_per_call: int
    tolerances: Tolerances
    sources: SourcePatterns
    gateway: Optional[Gateway] = None  # None: use ANTHROPIC_API_KEY and the public API

    @classmethod
    def from_file(cls, path: Path) -> "ReconConfig":
        """Read and validate a JSON configuration file."""
        logger.info("Loading configuration from %s", path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            tol = raw["tolerances"]
            config = cls(
                fund_id=str(raw["fund_id"]),
                model=str(raw.get("model", REQUIRED_MODEL)),
                effort=str(raw.get("effort", "medium")),
                max_workers=int(raw.get("max_workers", 4)),
                csv_rows_per_call=int(raw["extraction"]["csv_rows_per_call"]),
                mt940_statements_per_call=int(raw["extraction"]["mt940_statements_per_call"]),
                dates_per_call=int(raw["reconciliation"]["dates_per_call"]),
                tolerances=Tolerances(
                    cash=Decimal(tol["cash"]),
                    holding_quantity=Decimal(tol["holding_quantity"]),
                    market_value=Decimal(tol["market_value"]),
                    price_bps=Decimal(tol["price_bps"]),
                    email_closing=Decimal(tol["email_closing"]),
                ),
                sources=SourcePatterns(**raw["sources"]),
                gateway=Gateway(**raw["gateway"]) if raw.get("gateway") else None,
            )
        except FileNotFoundError as exc:
            raise ConfigError(f"configuration file not found: {path}") from exc
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ConfigError(f"invalid configuration in {path}: {exc!r}") from exc

        if config.max_workers < 1 or min(
            config.csv_rows_per_call, config.mt940_statements_per_call, config.dates_per_call
        ) < 1:
            raise ConfigError("max_workers and all chunk sizes must be at least 1")
        if config.effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ConfigError(f"unknown effort level: {config.effort}")

        logger.info("Configuration loaded for fund %s (model %s)", config.fund_id, config.model)
        return config
