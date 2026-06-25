# vmctl depends on sss for file-sync; sync reads a live guest, never boots it

## Status

accepted (consumer side of sss [ADR-0004](../../sss/docs/adr/0004-standalone-no-vm-coupling.md), which inverted the original sss→vmctl dependency)

## Context

`sss` was decoupled from VMware and made standalone and target-agnostic: it
reaches a machine over SSH from an explicitly supplied host + credentials and
contains no VM knowledge (sss ADR-0004). That inverts the dependency — the
VM-control tool now depends on the sync tool, not the reverse.

vmctl already owns everything sss needs to be pointed at a VM: name-based
resolution (incl. single-running auto-select), the live guest IP
(`network.ip()`), and per-VM guest credentials in `~/.vmctl/config.json`. So
vmctl can *inherit* sss's sync/push/exec/primitives by composition instead of
reimplementing file transfer.

Two frictions shape the seam:

- **The guest IP is not reliably available.** `network.ip()` returns `""` until a
  DHCP lease lands, reports a **stale** last-known IP on a suspended VM, and
  raises on a powered-off VM (see CONTEXT.md "Guest IP" / "Stale guest IP").
- **vmctl already sets a precedent of commands owning VM power** — `snapshot
  revert` hard-stops/reverts/starts for you ([ADR-0002](0002-snapshot-revert-owns-lifecycle.md)).
  A reader could reasonably expect `vmctl sync` to boot the VM too.

## Decision

**vmctl depends on sss** (embedded as a git submodule at `./sss`, installed
editable) and exposes file-sync as a `SyncModule` on `VM`:

- `vm.sync.run(...)` — full profile lifecycle (pre_sync → sync → post_sync).
- `vm.sync.push(source, dest)` — ad-hoc, profile-less transfer.

CLI surface is **`vmctl sync` + `vmctl push` only** (not the full sss verb set).
`SyncModule` resolves the guest IP and reuses the VM's stored credentials as the
SSH login, then calls `sss.connect(host=ip, user=…, password=…)`. The `import
sss` is **lazy** (VM commands work without sss/paramiko installed) and
`sss.SssError` is wrapped into `VMCtlError` so vmctl's CLI error surface stays
uniform.

**`vmctl sync` reads the live guest once and never boots the VM.** It requires
`PowerState == "on"` and a non-empty `network.ip()`; otherwise it raises an
actionable error telling the caller to start the VM / wait for a lease. No
power lifecycle, no IP polling.

**Build-config / arch are not vmctl flags.** `vmctl sync` exposes only
`--optional` and `--project-dir`; `{build_cfg}`/`{arch}` substitution comes from
the selected profile's own `variables` block in `~/.sss/config.json`. vmctl
passes no extra substitution vars.

## Considered options

- **Poll for the IP and/or auto-boot the VM in `vmctl sync`** (mirroring
  ADR-0002's lifecycle ownership) — rejected. A suspended VM's IP is stale and a
  cold boot can take minutes with no reliable "desktop ready" signal short of the
  Tools gate; baking that wait into a sync command hides latency and failure
  modes. Reverting is a discrete, fast, idempotent operation that *benefits* from
  lifecycle ownership; "sync into whatever is running" does not. The caller (or a
  future explicit harness) decides when the guest is ready.
- **Mirror sss's full CLI under vmctl** (`exec`/`service`/`process`/`files`) —
  rejected: re-creates two near-identical CLIs and re-introduces "vmctl knows
  every sss verb" coupling. The library inherits the whole session anyway via
  `sss.connect`; only the high-value `sync`/`push` convenience is surfaced.
- **Expose `--debug/--release/--arch` on `vmctl sync`** — rejected: those are
  sync-profile concerns; duplicating them on the VM tool's CLI spreads the same
  knob across two tools. Profiles already carry a `variables` default.

## Consequences

- vmctl gains a real dependency on sss (path/editable install); README documents
  `git submodule update --init` → `pip install -e ./sss` → `pip install -e .`.
- `vmctl sync`/`push` fail fast on a not-running or lease-less VM instead of
  hanging or syncing to a stale address — the no-boot rule is a deliberate
  divergence from the ADR-0002 lifecycle precedent and is documented as such.
- A new live integration prerequisite: the `vmctl-unittest` `init` snapshot must
  run an OpenSSH server reachable as `test`/`test` (sss is SSH-only). Recorded in
  tests/INTEGRATION.md.
