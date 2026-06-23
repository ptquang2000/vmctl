# `snapshot revert` owns the stop/revert/start lifecycle

## Status

accepted (supersedes the library-side intent of project findings #5 and #15 for revert)

## Context and decision

`vmcli Snapshot Revert` errors while the VM is "online" (running/paused) and
tolerates only off/suspended states. The original design (project finding #15,
*"library stays faithful to vmcli constraints; harness owns lifecycle"*) had the
library `revert()` surface that "must be off" error and left stopping the VM to
the caller — the integration harness did a manual hard-stop before reverting.

We decided to **move the lifecycle into the library** and restore prior power
state:

| Prior state | `SnapshotModule.revert(name)` |
|---|---|
| Online (running/paused) | hard-stop → revert → start (ends running) |
| Suspended | revert only (stays suspended) |
| Off | revert only (stays off) |

The snapshot name is **resolved/validated first**, so a typo never powers off the
VM. The stop is **hard** because revert discards the running state anyway — a
graceful guest shutdown would be wasted effort and can hang without Tools.
`revert(name, ensure_running=True)` forces a start regardless of prior state; the
**CLI `snapshot revert` passes this**, so the command always ends running
(suspended → resume, off → cold boot).

## Considered options

- **Keep the library faithful (errors when online); add the stop only in the CLI**
  — preserves #15, but two consumers (CLI + harness) would each re-implement the
  same lifecycle. Rejected: the convenience belongs with the operation.
- **Soft stop** before revert — pointless here since the state is discarded, and
  it adds a Tools dependency and hang risk.

## Consequences

- The library is no longer faithful to the vmcli "must be off" constraint for
  revert; findings #5 and #15 are superseded for this path. API consumers calling
  `revert()` on a running VM now get an auto-stop instead of an error.
- `SnapshotModule` gains a dependency on power operations (Power query + stop +
  start) — it must hold or construct a `PowerModule`.
- Snapshot unit tests that asserted the bare single vmcli revert call must be
  updated for the extra state-query/stop/start calls.
