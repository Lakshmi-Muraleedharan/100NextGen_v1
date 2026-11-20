# Reconciliation exceptions for human review - FUND01

8 item(s) need review.

## Patterns
- Items on the same date may share a cause.

## Check statistics

| Check | Compared | Matched | Open |
|---|---:|---:|---:|
| cash_ledger_vs_bank | 43 | 39 | 4 |
| cash_movement_vs_prime_broker | 42 | 42 | 0 |
| email_closing_vs_ledger | 2 | 2 | 0 |
| holdings_admin_vs_custody | 172 | 170 | 2 |
| market_value_recalculation | 172 | 172 | 0 |
| price_admin_vs_vendor | 172 | 170 | 2 |
| statement_integrity | 85 | 85 | 0 |

## Open items

### 1. [HIGH] cash_ledger_vs_bank - 2026-10-07 - ACC1001
- Status: **BREAK** (agreed)
- admin_ledger: 993000.00  |  bank_closing: 994250.00  |  difference: -1250.00
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 2. [HIGH] cash_ledger_vs_bank - 2026-10-08 - ACC1001
- Status: **BREAK** (agreed)
- admin_ledger: 997000.00  |  bank_closing: 998250.00  |  difference: -1250.00
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 3. [HIGH] cash_ledger_vs_bank - 2026-11-06 - ACC1001
- Status: **BREAK** (agreed)
- admin_ledger: 993000.00  |  bank_closing: 994250.00  |  difference: -1250.00
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 4. [HIGH] cash_ledger_vs_bank - 2026-11-09 - ACC1001
- Status: **BREAK** (agreed)
- admin_ledger: 997000.00  |  bank_closing: 998250.00  |  difference: -1250.00
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 5. [HIGH] holdings_admin_vs_custody - 2026-10-15 - CUST2001/ZZ0000000002
- Status: **BREAK** (agreed)
- admin_quantity: 3000  |  custody_quantity: 3010  |  difference: -10
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 6. [HIGH] holdings_admin_vs_custody - 2026-11-16 - CUST2001/ZZ0000000002
- Status: **BREAK** (agreed)
- admin_quantity: 3000  |  custody_quantity: 3010  |  difference: -10
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 7. [HIGH] price_admin_vs_vendor - 2026-10-23 - ZZ0000000003
- Status: **BREAK** (agreed)
- admin_price: 41.8140  |  vendor_price: 41.9367  |  difference: 29.26
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.

### 8. [HIGH] price_admin_vs_vendor - 2026-11-24 - ZZ0000000003
- Status: **BREAK** (agreed)
- admin_price: 41.9245  |  vendor_price: 41.6408  |  difference: 68.13
- Likely cause: Cannot tell from the data.
- Suggested action: Check the source records.
