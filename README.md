# Fund Reconciliation (Claude)

Same functionality as `..\fund_reconciliation`, but **extraction, reconciliation and report
generation are done by `claude-sonnet-5-5` (gateway alias `claude-sonnet-5-5--VNGC`)**. The output is:

- **Failed reconciliations for human review**: `break_queue.csv` + `review_report.md`
- **Investor statement** built only from figures that reconciled: `.md` and `.html`

## Pipeline

```
source feeds ──► 1 Extract (Claude) ──► 2 Reconcile (Claude) ──► verify vs control ──┬─► break_queue.csv + review_report.md  (Claude)
 (CSV/MT940/eml)   validated records      7 checks, per window     agree / REVIEW    └─► investor_statement_*.md/.html       (Claude)
```

| Stage | What Claude does | Guard in code |
|---|---|---|
| Extract | Reads each CSV / MT940 / email and returns structured records (JSON-schema constrained) | row/statement counts must match; ids and dates must appear verbatim in the source; every amount must be a number present in the source; one retry with feedback, then the run fails |
| Reconcile | Derives every comparison for the 7 checks, does the arithmetic, decides MATCHED / BREAK / MISSING | `control.py` recomputes everything independently. Any disagreement, omitted, invented or duplicated comparison becomes status `REVIEW` and goes to the human queue. Figures in outputs always come from the control's arithmetic |
| Review report | Explains each open item: priority, likely cause, next step, cross-item patterns | refs must be covered; uncovered items are flagged for manual review |
| Investor statement | Writes the narrative | tables/figures are rendered by code; any number in the prose that is not in the facts is rejected (one retry, then no statement) |

A statement is only issued from a business day on which **every** comparison reconciled; days with an
open item are excluded from the statement and mentioned only as "pending verification" (no details).

## Setup and run

```powershell
pip install -r requirements.txt
# SPN VNGC-0942_5593_LLM_SPN credentials (used to read the API key from Azure Key Vault)
$env:AZURE_TENANT_ID = "..."
$env:AZURE_CLIENT_ID = "..."
$env:AZURE_CLIENT_SECRET = "..."
python -m recon_claude --input ..\sample-data --output output
```

The `gateway` block in `config.json` points at the LLM gateway (`https://llmproxy.ustdev.com/`) and the
Key Vault secret (`VNGC1-kvs`); the model is the gateway alias `claude-sonnet-5-5--VNGC`. Remove the
`gateway` block to call the public API with `ANTHROPIC_API_KEY` instead.

`-v` for debug logging. Settings (model, effort, chunk sizes, tolerances, file patterns) are in `config.json`.

Expected on the sample feeds: 4 open items (cash 7 & 8 Oct, holdings 15 Oct, price 23 Oct), investor
statement as at 2026-10-30.

## Test (no API key needed)

```powershell
python -m unittest discover -s tests -v
```

Tests use a fake Claude (`tests/fake_claude.py`) that answers correctly, plus fault injection: dropped
rows, altered amounts, a model hiding a break, omitted comparisons, invented numbers in the statement.

## Outputs

| File | Purpose |
|---|---|
| `break_queue.csv` | open items: BREAK / MISSING / REVIEW with both values, status from Claude and the control, priority, likely cause, suggested action |
| `review_report.md` | Claude's analysis for the review team |
| `investor_statement_<fund>_<date>.md/.html` | investor statement |
| `reconciliation_results.csv` | every comparison, for audit |
| `extracted_records.json` | what Claude extracted from each file |
| `summary.json` | status, counts, verification outcomes, token usage, SHA-256 of inputs |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Run completed; exceptions are in the break queue |
| 2 | Run did not complete: config, missing/unreliable source, or Claude API failure/refusal |
| 3 | Reconciliation done and `break_queue.csv` written, but a narrative report failed |

## Design notes and limits

- The prototype's design rule was "no model decides whether records match". Here Claude does decide,
  so every decision is cross-checked against the prototype's deterministic logic (`control.py`).
  This costs nothing at run time and guarantees a model slip becomes a human-review item, never a pass.
- Claude calls use schema-constrained JSON output, streaming, no sampling parameters. A refusal or
  truncated reply raises an error; no fallback model is used so that everything stays on `claude-sonnet-5-5--VNGC`.
- The sample data has no investor register, so the statement is **fund level** (same statement for all
  investors). Per-investor statements need subscription/holder data as an additional feed.
- The total in the statement is cash + securities, explicitly not NAV (no liabilities/accruals feed).
- Not run against the live API in development (no credentials available); the SDK call shape was
  checked against the installed `anthropic` package and everything else is covered by the fake-Claude tests.
