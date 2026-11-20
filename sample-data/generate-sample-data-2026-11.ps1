param([Parameter(Mandatory = $true)][string]$Root)
# Generates SYNTHETIC sample files for November 2026, continuing from the October 2026 files in $Root.
# Identifiers, names and amounts are invented for testing. ISINs use the ZZ prefix and are not valid real codes.
$ErrorActionPreference = 'Stop'
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($dir in 'admin', 'custodian', 'bank', 'prime_broker', 'pricing', 'email') {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
}

function Save-Text([string]$rel, [string]$text) {
    [System.IO.File]::WriteAllText((Join-Path $Root $rel), $text, $utf8)
}
function Fmt([double]$x) { $x.ToString('0.00', $inv) }
function FmtMt([double]$x) { (Fmt $x).Replace('.', ',') }
function P4([double]$x) { $x.ToString('0.0000', $inv) }

function Get-BusinessDays([int]$year, [int]$month) {
    $list = New-Object System.Collections.Generic.List[datetime]
    $d = [datetime]::new($year, $month, 1)
    while ($d.Month -eq $month) {
        if ($d.DayOfWeek -ne 'Saturday' -and $d.DayOfWeek -ne 'Sunday') { $list.Add($d) }
        $d = $d.AddDays(1)
    }
    return , $list
}

$octDays = Get-BusinessDays 2026 10
$days = Get-BusinessDays 2026 11
$offset = $octDays.Count   # continue the price/flow pattern from where October stopped

# Opening balances = October closing balances
$octCash = Import-Csv -LiteralPath (Join-Path $Root 'admin\admin_cash_ledger_2026-10.csv')
$openingLedger = [double]($octCash[-1].ledger_balance)
$octMt = Get-Content -LiteralPath (Join-Path $Root 'bank\bank_statement_mt940_2026-10.txt') -Raw
$m62 = [regex]::Matches($octMt, ':62F:C\d{6}USD([\d,]+)')
$bankOpening = [double]($m62[$m62.Count - 1].Groups[1].Value.Replace(',', '.').Replace('.', '')) / 100

$fund = 'FUND01'
$cashAcct = 'ACC1001'
$custAcct = 'CUST2001'
$secs = @(
    @{ id = 'ZZ0000000001'; name = 'SAMPLE TECH PLC';   base = 182.40; qty = 5000 },
    @{ id = 'ZZ0000000002'; name = 'SAMPLE BANK CORP';  base = 64.15;  qty = 3000 },
    @{ id = 'ZZ0000000003'; name = 'SAMPLE ENERGY INC'; base = 41.80;  qty = 1200 },
    @{ id = 'ZZ0000000004'; name = 'SAMPLE HEALTH LTD'; base = 97.25;  qty = 800 }
)

function Get-Price([int]$i, [int]$kg) {
    [math]::Round($secs[$i].base * (1 + 0.004 * [math]::Sin($kg * ($i + 1) * 0.7)), 4)
}
function Get-Flow([int]$kg) {
    [double]((((($kg * 37) % 11) - 5) * 1000))
}

$cashCsv = New-Object System.Text.StringBuilder
[void]$cashCsv.AppendLine('as_of_date,fund_id,account_id,currency,ledger_balance,extract_run_id')
$admHold = New-Object System.Text.StringBuilder
[void]$admHold.AppendLine('as_of_date,fund_id,account_id,security_id,security_name,quantity,admin_price,currency,market_value,extract_run_id')
$custSb = New-Object System.Text.StringBuilder
[void]$custSb.AppendLine('as_of_date,custodian_account,security_id,quantity,currency,settlement_status,file_reference')
$vendorSb = New-Object System.Text.StringBuilder
[void]$vendorSb.AppendLine('price_date,security_id,security_name,currency,close_price,price_source')
$pbSb = New-Object System.Text.StringBuilder
[void]$pbSb.AppendLine('activity_date,prime_account,fund_id,txn_type,reference,currency,amount')
$mtSb = New-Object System.Text.StringBuilder

$ledger = $openingLedger
$bankClose = $bankOpening
$prevDiff = 0.0

for ($k = 0; $k -lt $days.Count; $k++) {
    $dt = $days[$k]
    $kg = $k + $offset
    $ds = $dt.ToString('yyyy-MM-dd', $inv)
    $yy = $dt.ToString('yy', $inv)
    $mmdd = $dt.ToString('MMdd', $inv)
    $compact = $dt.ToString('yyyyMMdd', $inv)

    # Cash: ledger moves by the day's net flow
    $flow = Get-Flow $kg
    $ledger = [math]::Round($ledger + $flow, 2)

    # Bank: same flow, plus a 1,250.00 bank-side difference on days 5 and 6 (planted break)
    $diffNow = 0.0
    if ($k -ge 4 -and $k -lt 6) { $diffNow = 1250.00 }
    $bankOpen = $bankClose
    $bankFlow = $flow + ($diffNow - $prevDiff)
    $bankClose = [math]::Round($bankOpen + $bankFlow, 2)
    $prevDiff = $diffNow

    [void]$cashCsv.AppendLine("$ds,$fund,$cashAcct,USD,$(Fmt $ledger),RUN-$compact")
    [void]$pbSb.AppendLine("$ds,$cashAcct,$fund,NET_SUB_RED,PB-$compact,USD,$(Fmt $flow)")

    $cdFlow = 'C'
    if ($bankFlow -lt 0) { $cdFlow = 'D' }
    [void]$mtSb.AppendLine('{1:F01SAMPLEBANKXXXX0000000000}{2:I940SAMPLEFUNDXXXXN}{4:')
    [void]$mtSb.AppendLine(":20:STMT$yy$mmdd")
    [void]$mtSb.AppendLine(":25:SAMPLE/$cashAcct")
    [void]$mtSb.AppendLine(":28C:$($k + 1)/001")
    [void]$mtSb.AppendLine(":60F:C$yy${mmdd}USD$(FmtMt $bankOpen)")
    [void]$mtSb.AppendLine(":61:$yy$mmdd$cdFlow$(FmtMt ([math]::Abs($bankFlow)))NTRFNONREF")
    [void]$mtSb.AppendLine(":86:SAMPLE NET SUBSCRIPTION REDEMPTION $cashAcct")
    [void]$mtSb.AppendLine(":62F:C$yy${mmdd}USD$(FmtMt $bankClose)")
    [void]$mtSb.AppendLine('-}')

    for ($i = 0; $i -lt $secs.Count; $i++) {
        $sec = $secs[$i]
        $price = Get-Price $i $kg
        # Admin uses a stale (previous day) price for security 3 on day 17 (planted price break)
        $admPrice = $price
        if ($k -eq 16 -and $i -eq 2) { $admPrice = Get-Price $i ($kg - 1) }
        $admMv = [math]::Round($sec.qty * $admPrice, 2)
        [void]$admHold.AppendLine("$ds,$fund,$custAcct,$($sec.id),$($sec.name),$($sec.qty),$(P4 $admPrice),USD,$(Fmt $admMv),RUN-$compact")

        # Custodian holds 10 extra units of security 2 on day 11 (planted quantity break)
        $custQty = $sec.qty
        if ($k -eq 10 -and $i -eq 1) { $custQty = $sec.qty + 10 }
        [void]$custSb.AppendLine("$ds,$custAcct,$($sec.id),$custQty,USD,SETTLED,CUST-$compact")

        [void]$vendorSb.AppendLine("$ds,$($sec.id),$($sec.name),USD,$(P4 $price),SAMPLE_VENDOR")
    }
}

$lastDay = $days[$days.Count - 1]
$net = [math]::Round($ledger - $openingLedger, 2)
$openStr = Fmt $openingLedger
$netStr = Fmt $net
$closeStr = Fmt $ledger
$dateHdr = $lastDay.ToString('ddd, dd MMM yyyy', $inv)
$eml = @"
From: prime-broker-ops@primebroker.example.com
To: fund-ops@fund.example.com
Date: $dateHdr 18:05:00 +0000
Subject: FUND01 month-end cash summary 2026-11 (synthetic sample)
Content-Type: text/plain; charset=utf-8

Dear fund operations team,

Month-end cash summary for FUND01, account ACC1001, November 2026.

Opening cash (1 Nov 2026):           $openStr USD
Net subscriptions/redemptions:       $netStr USD
Closing cash ($($lastDay.ToString('d MMM yyyy', $inv))):    $closeStr USD

Business days covered: $($days.Count)
Please reconcile against your ledger and let us know of any differences.

Regards,
Prime brokerage operations (sample)
"@

Save-Text 'admin\admin_cash_ledger_2026-11.csv' $cashCsv.ToString()
Save-Text 'admin\admin_holdings_2026-11.csv' $admHold.ToString()
Save-Text 'custodian\custodian_positions_2026-11.csv' $custSb.ToString()
Save-Text 'bank\bank_statement_mt940_2026-11.txt' $mtSb.ToString()
Save-Text 'prime_broker\prime_broker_activity_2026-11.csv' $pbSb.ToString()
Save-Text 'pricing\vendor_prices_2026-11.csv' $vendorSb.ToString()
Save-Text 'email\prime_broker_month_end_summary_2026-11.eml' $eml

Write-Output ("Business days: {0} ({1} to {2})" -f $days.Count, $days[0].ToString('yyyy-MM-dd', $inv), $lastDay.ToString('yyyy-MM-dd', $inv))
Write-Output ("Opening ledger from Oct: {0}; opening bank from Oct MT940: {1}" -f (Fmt $openingLedger), (Fmt $bankOpening))
Write-Output ("Closing ledger: {0}" -f $closeStr)
