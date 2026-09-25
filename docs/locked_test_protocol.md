# Locked Test Protocol
**Data version:** 20260918-010-572728d9 (synthetic fixture — point-in-time
artifact; the REAL 15m dataset `20260918-010+8f120133-1ba57af7` has its own
locked partition recorded in `data/evidence/impulse_research_xauusd_dukascopy_15m.json`)

- Partitions: discovery 300 (60%), validation 100 (20%), locked 100 (20%)
- Immutable: hash sha256:572728d92ebb5c2a, once created cannot change
- Locked test never influences design/params/thresholds/feature selection
- Prevent accidental access via LockedTestPartitioner.get_locked(allow=False) → violation, every attempt logged: []
- Freeze: strategy spec/params/features/execution/risk frozen after discovery, only then locked test executed one-shot unless protocol violation documented
- Record every attempt to access/modify locked-test artifacts

