# Desktop observation artifact: history-hygiene decision

Inspection date: 2026-09-18.

## Decision

**A narrow reachable-history purge is warranted.** The repository is public, the raw Desktop artifact was supplied for temporary review, and authority to redistribute the broker-derived market observations publicly has not been established. Ordinary deletion still permits downloading the original upload through its historical commit. Keeping the raw object in public branch history conflicts with that temporary-review purpose.

Real market observations are not automatically a secret, and this review does not assert a licensing violation or credential breach. The inspected metadata contains no credential-shaped/login keys; nevertheless the file contains observation times, ten full price payloads, session/source metadata and row-level records. Data minimization is sufficient reason to remove the accidental publication from reachable project history. Preserve a hash and bounded audit findings instead of the raw artifact.

## Exact inspected scope

- File: `FS-5a9542.session_evidence.json` (572,951 bytes).
- Blob ID: `601c5e6e70c813eaad5fa136bcbb24f9305d644b`.
- File SHA-256: `61ba66e9e36ac04221ae4e2615e740d3758999eb52e6d885d894dd669782145c`.
- Upload-only commit: `4c31af0babfb2b1a59d0c18ca07ddbd30f6bd41b`.
- Deletion-only commit: `290051e95b660b2fc42c8335fd53fbbd7d1d9a32`.
- Last clean ancestor: `ae99eae` (UI modernization).
- The tree at `290051e` is **identical** to the tree at `ae99eae`. Neither upload nor deletion contains legitimate project code changes to preserve.

All advertised GitHub refs were inspected, including PR refs:

| Ref | Upload commit or raw blob reachable before cleanup? |
|---|---|
| `refs/heads/arena/01a0b075-trading-system` | **Yes** |
| `refs/heads/main` | No |
| `refs/heads/arena/01a0aa13-trading-system` | No |
| `refs/heads/arena/01a0aafd-trading-system` | No |
| `refs/heads/arena/01a0af7d-trading-system` | No |
| `refs/pull/1/head` | No |
| `refs/pull/1/merge` | No |

There were no advertised tags and GitHub reported zero forks at inspection. This does not exclude private clones, downloaded copies, hidden refs or platform caches.

## Narrow rewrite procedure and safeguards

Only `arena/01a0b075-trading-system` may be rewritten. The legitimate ancestor history through `ae99eae` is preserved byte-for-byte, including its commit IDs. Drop the upload-only and deletion-only commits and attach the verified hardening change directly to that clean ancestor, retaining the exact final project tree. No other branch, tag or PR ref is force-updated. No blanket filtering of unrelated history is necessary.

Before the destructive update, report the old session-branch tip, candidate clean tip and parent, the two removed commits, and the exact force-with-lease scope. Verify identical old/candidate final trees and absent raw blob in candidate reachability. Update the existing local session branch only; push with an explicit lease against the inspected remote tip `290051e95b660b2fc42c8335fd53fbbd7d1d9a32`. A concurrent remote update must cause refusal rather than be overwritten. Compare all advertised refs afterwards to ensure only the intended branch moved.

A repository-wide `*.session_evidence.json` ignore rule now prevents ordinary accidental `git add` of these exports in any directory. It does not block GitHub's web uploader or `git add -f`; contributors must not use either to republish raw evidence. Transfer future artifacts through a private, access-controlled channel outside project Git history.

## What this cleanup cannot guarantee

A branch rewrite removes **reachability through advertised project history**, not every copy of the data. Old commit/blob URLs can remain accessible in GitHub's object storage, caches or hidden refs after a force push. Existing clones and downloaded artifacts are not recalled. Local unreachable objects and recovery reflogs may also retain the old history; no repository-wide reflog expiration or aggressive garbage collection is performed because it could destroy unrelated recoverable work.

If permanent public removal is required, the repository owner must coordinate with GitHub Support about the old commit/blob URLs and any cached/hidden copies. Do not claim successful server-side erasure based solely on `git ls-remote` or a clean branch tree. After coordination, collaborators should re-clone or carefully discard only the retired session-branch history, rather than merge/push it back. Any local garbage collection should happen after safe backup/recovery review and must not be confused with removal from GitHub.

The final task report records the published clean commit, ref verification and any remaining direct object accessibility. No credential rotation is asserted necessary from this artifact alone. No execution permission follows from either this cleanup or artifact verification.
