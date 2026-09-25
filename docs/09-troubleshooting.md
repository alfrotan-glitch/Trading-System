# 9. Troubleshooting & Diagnostics

## Common Diagnostics & Resolutions

### 1. MT5 Terminal Unreachable
- **Symptom:** `readiness passed: False blockers=['MT5 not installed', 'Terminal not running']`
- **Root Cause:** MetaTrader 5 terminal process is not running or terminal path is incorrect.
- **Resolution:**
  1. Ensure MetaTrader 5 terminal is installed and open on the host machine.
  2. Verify terminal path points to `terminal64.exe`:
     ```json
     {
       "terminal_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
     }
     ```
  3. Ensure `python -m qts.cli demo connectivity` returns `terminal_reachable: True`.

---

### 2. Symbol Mapping Refusal (`XAUUSD` vs `XAUUSD@`)
- **Symptom:** `canonical symbol XAUUSD has no broker mapping (e.g. XAUUSD@) — refusing`
- **Root Cause:** Broker Market Watch names the gold instrument with an alias (e.g. `XAUUSD@`, `GOLD#`), but no symbol map is declared.
- **Resolution:**
  Declare the symbol map in `data/setup/mt5_setup.json`:
  ```json
  {
    "symbol": "XAUUSD",
    "symbol_map": {
      "XAUUSD": "XAUUSD@"
    }
  }
  ```
  Ensure `XAUUSD@` is visible in MT5 Market Watch (`Ctrl+M`).

---

### 3. Market Data Stale / Age Exceeded
- **Symptom:** Pre-trade gate fails with `market_data_fresh: tick age X.XXs > 5.00s`.
- **Root Cause:** Market is closed (weekend / holiday / daily rollover 21:00–22:00 UTC) or system clock is out of sync.
- **Resolution:**
  1. Verify gold trading hours (London–New York overlap: Monday 08:00 UTC to Friday 16:00 UTC).
  2. Ensure operating system clock is synchronized via NTP.

---

### 4. Authority Readiness TTL Expired
- **Symptom:** `durable execution permission is not in force — its readiness evidence expired`
- **Root Cause:** Demo execution authority decays after 120 seconds to guarantee fresh broker facts before order submission.
- **Resolution:**
  Re-verify authority against live terminal:
  ```bash
  qts demo reverify --confirm --risk-ack
  ```

---

### 5. Reconciliation Drift Suspension
- **Symptom:** `reconciliation: QUANTITY_MISMATCH or MISSING_POSITION`
- **Root Cause:** Internal portfolio positions disagree with venue tickets reported by MT5.
- **Resolution:**
  1. Inspect open positions via CLI:
     ```bash
     qts demo positions
     ```
  2. If manual positions were opened directly in the terminal, close them to restore alignment.
  3. Re-run connectivity to synchronize broker deals:
     ```bash
     qts demo connectivity
     ```
