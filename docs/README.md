# QTS Documentation

These ten guides are the operating documentation. Read [`QTS_PROJECT_CONTROL.md`](../QTS_PROJECT_CONTROL.md) before changing architecture.

Files that remain beside these guides are cited by code or by an operator setup path. Dated research records live in [evidence/](evidence/README.md). They are not operating manuals, and they do not authorize a trade.

---

## Canonical Guides

1. [**01. Product Overview**](01-product-overview.md)  
   Mission, core principles, truth in measurements, and product mental model.

2. [**02. System Architecture**](02-architecture.md)  
   Subsystem boundaries, domain models, execution pipeline, and data flow.

3. [**03. Getting Started**](03-getting-started.md)  
   Prerequisites, environment setup, dependencies, configuration, and startup.

4. [**04. Operating QTS**](04-operating-qts.md)  
   Reading the Executive Dashboard, operational workflows, and emergency controls.

5. [**05. Research & Validation**](05-research-and-validation.md)  
   Hypothesis preregistration, statistical defense (DSR/Holm), walk-forward validation, and the forward registry.

6. [**06. Demo Trading Workflow**](06-demo-trading.md)  
   The 12-step operational trade lifecycle: connect, bind, quote, preflight, order, deal sync, reconcile, monitor, close, audit.

7. [**07. Risk Controls & Safety**](07-risk-and-safety.md)  
   Fail-closed posture, 22 pre-trade safeguard checks, exposure limits, and reconciliation mechanics.

8. [**08. Live Trading Governance**](08-live-trading-governance.md)  
   Structural live boundary, multi-signature approval prerequisites, and immutable revocation sidecars.

9. [**09. Troubleshooting & Diagnostics**](09-troubleshooting.md)  
   Terminal connectivity, symbol mapping, stale data, readiness TTL, and reconciliation drift resolution.

10. [**10. Developer Guide**](10-developer-guide.md)  
    Directory structure, strategy implementation standards, and testing procedures.

---

## Technical Specifications & Setup Guides

- [Desktop Installation (Windows)](desktop_installation_windows.md)
- [MT5 Demo Setup](mt5_demo_setup.md)
- [UI Design System Specification](evidence/ui_design_system.md)
- [Troubleshooting on Windows](troubleshooting_windows.md)
