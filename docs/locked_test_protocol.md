# Locked Test Protocol
**Data version:** 20260918-010-572728d9

- Partitions: discovery 300 (60%), validation 100 (20%), locked 100 (20%)
- Immutable: hash sha256:572728d92ebb5c2a, once created cannot change
- Locked test never influences design/params/thresholds/feature selection
- Prevent accidental access via LockedTestPartitioner.get_locked(allow=False) → violation, every attempt logged: []
- Freeze: strategy spec/params/features/execution/risk frozen after discovery, only then locked test executed one-shot unless protocol violation documented
- Record every attempt to access/modify locked-test artifacts

