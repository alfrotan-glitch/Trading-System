from pathlib import Path
import json, re, hashlib
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
class Text(HTMLParser):
    def __init__(self): super().__init__(); self.items=[]
    def handle_data(self,data):
        if data.strip(): self.items.append(data.strip())
def parse_report(path):
    parser=Text(); parser.feed(path.read_text(encoding='utf-16')); items=parser.items
    keys=['History Quality:','Total Net Profit:','Profit Factor:','Expected Payoff:','Total Trades:','Equity Drawdown Maximal:','Sharpe Ratio:']
    return {key:items[items.index(key)+1] for key in keys if key in items}
def build():
    first=json.loads((ROOT/'evidence/research/development.json').read_text())
    second=json.loads((ROOT/'evidence/alternatives/development.json').read_text())
    rows=[]
    for result in (first,second):
        for family,m in result['metrics'].items():
            pf='n/a' if m['profit_factor'] is None else f"{m['profit_factor']:.2f}"
            lower='n/a' if m['day_block_bootstrap_99pct_lower_expectancy'] is None else f"{m['day_block_bootstrap_99pct_lower_expectancy']:.2f}"
            rows.append(f"| {family} | {m['trades']} | {m['net_usd']:.2f} | {pf} | {m['max_marked_drawdown_usd']:.2f} | {lower} | Reject |")
    native=ROOT/'evidence/native/native_development_2025.htm'
    native_text='Six-month final-build native run completed on 99% real ticks: 28,969,323 ticks, 11,460 bars, zero trades, unchanged $10,000 balance. This is not a return estimate; the absence of fills is unexplained. A separate eight-day diagnostic replay of the same code path accepted 10009 limits, filled and managed them, showing the Tester gate works there; this does not explain the six-month discrepancy.'
    if native.exists():
        info=parse_report(native); native_text=('Six-month final-build native run completed on 99% real ticks: 28,969,323 ticks and 11,460 bars, with zero trades and a flat $10,000 balance. This is no performance estimate; its zero-trade cause is unexplained. A separate March diagnostic accepted seven 10009 pending orders, observed four deals/two trades, and lost $32.88 over 1,203,920 ticks. This confirms the tester entry path works in that sample but does not explain the six-month discrepancy.')
    text='''# QTS Gold Robot - Initial Development: performance and delivery evidence

The mandate is **not complete**. No tested strategy demonstrated a reliable
positive after-cost edge. The package is an installable, compiled research build;
new broker DEMO entries remain blocked by the evidence gate. Real money is blocked.

## Native EA execution

The interim March 2025 run used a custom symbol copied from WMMarkets XAUUSD@
cache, not an active broker connection: 3,771,581 real ticks, 1,932 bars, 100% real
tick quality, six completed trades, net -$4.65, profit factor 0.95, expected payoff
-$0.78, maximum equity drawdown $145.04 (1.44%). This is before extra hypothetical
commissions/slippage. Native ledger commission was zero; zero is not a verified
claim about historical broker charging. The symbol uses current cloned contract
settings and a simulated $10,000 USD account, 1:100 leverage, 100 ms tester delay.

'''+native_text+'''

Pending acceptance, delayed fills, stop/target exits, server expiry, and protective
cancellation were observed. The old 10009 failure is fixed: valid accepted tickets
are retained and fills are attributed only from deals. Receipt policy also passed
12 actual MQL script cases. This does not certify connected broker execution,
partial fills, disconnect recovery, queue behavior, or every adverse-event race.

## Reproducible hypothesis research

Development interval: 2024-09-19 through 2025-06-30. Both passes replayed the same
45,280,491 genuine exported bid/ask ticks across 200 trading days, independently
per strategy. There were zero missing tick days, zero bar intervals without ticks,
and zero rejected malformed/out-of-order ticks in that interval. Data hashes and
per-day coverage are in the JSON reports. The complete cached export contains
541 daily files (approximately 6.2 GB); this is not a claim of complete coverage
outside the evaluated interval.

| Hypothesis | Trades | Net USD | Profit factor | Max marked DD USD | 99% bootstrap lower expectancy USD/trade | Decision |
|---|---:|---:|---:|---:|---:|---|
'''+ '\n'.join(rows)+'''

The first six hypotheses use the preferred former-stop LIMIT entry. The final
three are distinct market-entry research alternatives; no market-entry fallback
was added to the EA. The trend research proxy is not an exact reproduction of the
EA's MT5 ADX/H1 implementation. Canonical EA performance is reported separately.

All candidate positions use executable bid/ask quotes. Limits require one tick
of penetration after submission, receive no favorable entry improvement, expire
after 30 minutes, and are cancelled across observed quote gaps longer than one
minute. Position gaps use the next executable stop quote. Market alternatives
include adverse entry slippage. Max hold is 180 minutes. No mid-price fills,
bar-high/low fill ordering guesses, or future-bar indicators are used.

Costs are explicit assumptions: $10 round-trip commission per lot and 0.05 price
units adverse exit slippage (plus 0.05 entry slippage for market alternatives).
Cost stress adds another $10/lot and 0.10 adverse exit price units. These are
sensitivity assumptions, not verified broker tariffs. Spread is already in
executable quotes. Financing/swap and complete historical contract/session
changes are unverified; therefore these results cannot certify all-in profitability.

Sizing is 0.25% of **current** equity with a 35% reserve and rounded-down lots,
starting at $10,000. The first protocol text says initial equity; the recorded
engine actually uses current equity. This discrepancy is disclosed rather than
silently changing the frozen protocol. Daily loss and permanent peak-drawdown
stops are 1.5% and 4%. Gaps/price movement can exceed those percentages. Stopped
strategies were not reset to manufacture a longer profitable sample. These are
individual strategy accounts, not a combined portfolio.

The 1,000-resample Monte Carlo uses whole trading-day blocks, including zero-trade
days, with fixed seed 6241024. Confidence bounds are screening diagnostics on a
selected development sample, not independent proof. Daily Sharpe, recovery,
regime and quarterly results, execution vetoes and stress totals are preserved in
the JSON. No parameter optimization was performed. Parameter-neighborhood and
walk-forward testing were not run because every candidate failed development.
Post-hoc favorable regime slices were not promoted.

Validation (2025-07-01 to 2026-05-31) and final holdout (2026-06-01 to 2026-10-23)
were **not performance-evaluated**. Exporting/hashing bars and ticks does not make
them an independent result. New hypotheses must be frozen before evaluating
validation, and the final holdout must remain a one-use acceptance check.

## Engineering, reproduction, and remaining work

- MetaEditor: zero errors and warnings; compiler evidence in `evidence/compile.log`.
- Native receipt test: `evidence/QTS_receipt_test.txt` (12 cases, zero failures).
- Installer succeeded inside `runtime/terminal`; log in `evidence/installer.log`.
- Python regression result is recorded in `evidence/pytest.txt`.
- Run `python research/research.py` and `python research/alternatives.py` to reproduce
  development research from the retained export. These require only Python's
  standard library. Protocols and engine hashes are retained with results.
- Native fixture creation uses `research/BuildTesterFixture.mq5`; it copies
  174,528 M1 bars and 29,434,622 original cached ticks for January-June 2025.
  `research/RunNativeValidation.ps1` reruns the prepared native configuration.
- The former duplicate package is archived; the current installer deploys one EA
  and its receipt module, validates checksums, and restores backups on failure.

Remaining blockers are a credible positive edge, verified historical costs and
execution distributions, native/independent-model agreement for any proposed
strategy, and connected DEMO fault injection. Historical midnight floating equity
cannot be reconstructed exactly after a late first attachment. Broker corrections
to old ledger rows need statement reconciliation. Simulated rejection/queue/partial
fill probabilities are not measured. Stops cannot guarantee a maximum loss.

Do not interpret clean compilation, passing tests, or a completed backtest as
production readiness. No profitable strategy or combined portfolio is claimed.
'''
    (ROOT/'docs/PERFORMANCE_REPORT.md').write_text(text,encoding='utf8')
if __name__=='__main__': build()
