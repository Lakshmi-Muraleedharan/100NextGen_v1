"""Command line: python -m recon_claude --input ..\\sample-data --output output

With a "gateway" block in config.json the API key is fetched from Azure Key Vault
(SPN credentials in AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET) and calls go
through the gateway. Without it, ANTHROPIC_API_KEY is used.

Exit codes:
  0  run completed; any exceptions are in break_queue.csv
  2  run did not complete: bad configuration, missing/unreliable source, or Claude API failure
  3  reconciliation completed and break_queue.csv is written, but a narrative report failed
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import ReconConfig
from .errors import ReconciliationError, ReportError
from .pipeline import run_reconciliation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger("recon_claude")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="recon_claude",
        description="Claude-driven fund reconciliation: extraction, reconciliation and reporting.",
    )
    parser.add_argument("--input", type=Path, default=Path("../sample-data"), help="folder with the source feeds")
    parser.add_argument("--output", type=Path, default=Path("output"), help="folder for the outputs")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.json", help="configuration file")
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        config = ReconConfig.from_file(args.config)
        result = run_reconciliation(config, args.input, args.output)
    except ReportError as exc:
        logger.error("Reconciliation done, report failed: %s", exc)
        return 3
    except ReconciliationError as exc:
        logger.error("Reconciliation not completed: %s", exc)
        return 2

    for name, path in result.outputs.items():
        logger.info("%-26s %s", name, args.output / path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
