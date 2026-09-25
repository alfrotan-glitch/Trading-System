# 3. Getting Started

## Prerequisites

- **Operating System:** Windows 10/11 (for native MT5 terminal execution) or Linux / macOS (for research, backtesting, paper trading, and development).
- **Python:** Version 3.11, 3.12, or 3.13.
- **Node.js (Optional):** Version 18+ for running UI unit tests (`npm test`).
- **MetaTrader 5 Terminal:** Installed and logged into a supported broker DEMO account (e.g. WM Markets, IC Markets).

---

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/alfrotan-glitch/Trading-System.git
cd Trading-System
```

### 2. Set Up Virtual Environment
```bash
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

---

## Configuration & Setup

### 1. Configure MT5 Connection
Launch the configuration wizard or edit `data/setup/mt5_setup.json`:
```bash
qts mode declare demo_execution
```

Ensure your broker-specific venue symbol alias is declared if your broker uses a suffix:
```json
{
  "symbol": "XAUUSD",
  "symbol_map": {
    "XAUUSD": "XAUUSD@"
  },
  "terminal_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
}
```

### 2. Configure Credentials
Set your credentials in your environment or local `.env` file (never commit credentials):
```bash
export QTS_MT5_LOGIN="12345678"
export QTS_MT5_PASSWORD="demo_password"
export QTS_MT5_SERVER="WMMarkets-Demo"
```

---

## Running QTS

### 1. Start the API & Web Workstation
```bash
python -m qts.api.server
```
Navigate to `http://localhost:8901` in your browser.

### 2. Verify System Readiness via CLI
```bash
qts demo verify
```
The triage command will report current readiness blockers and recommend the exact single next operator action.
