# Local MT5 IPC audit (2026-10-22)

## Verified environment

- Configured terminal: `C:\Program Files\MetaTrader 5\terminal64.exe`.
- Installed terminal file version: `5.0.0.6230` (build 6230).
- Python: 3.14.7 x64; `MetaTrader5` package: 5.0.6231.
- `data/setup/mt5_setup.json` declares `demo_execution` and maps `XAUUSD` to
  `XAUUSD@`. It contains no account or credential fields.
- One terminal process was present and reported responsive. Its main-window
  title was blank. The computer-use surface exposed no selectable app window.

## Connection result

Using the configured executable path, `mt5.initialize()` failed with
`(-10005, "IPC timeout")` at both a 2.5-second and a 60-second timeout. The
60-second result rules out only a short startup wait; it does not identify the
underlying cause. `terminal_info()` could not be queried because initialization
failed. Therefore the terminal's current account, server connection, and
DEMO-account status remain unverified.

The Python and terminal architectures match (both 64-bit), and the configured
path matches the installed terminal. A public MQL5 thread reports the same
terminal/API build pair with `-10005`, but also contains a successful test on
that pair. This is a lead, not evidence that the version pair is the cause.
MetaQuotes documents `-10005` as an internal timeout and `initialize()` as the
Python-to-terminal connection step.

## Safety and next check

No credentials or sensitive terminal configuration were read or changed. No
order API was called, no DEMO order was placed, and LIVE was not enabled. The
next useful check requires a visible, selectable MT5 window so its displayed
connection state can be inspected without changing settings or signing in.

Sources: [MetaQuotes `initialize()` reference](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py), [MetaQuotes `last_error()` reference](https://www.mql5.com/en/docs/python_metatrader5/mt5lasterror_py), [reported build-6230/API-5.0.6231 IPC case](https://www.mql5.com/en/forum/517401).
