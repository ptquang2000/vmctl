# Unified `peripheral connect`/`disconnect` resolving the device type via `list`

## Status

accepted

## Context and decision

`peripheral` had grown a separate command per device type and verb:
`connect-disk`/`disconnect-disk`, `connect-serial`/`disconnect-serial`,
`connect-usb`/`disconnect-usb`, plus `eject` and `mount-iso` — 9 verbs. The user
asked for a shorter surface where device types are not split across commands, and
for `list` to show the connectable devices.

We decided to collapse the six typed connect/disconnect verbs into **two**:
`peripheral connect <id>` and `peripheral disconnect <id>`. `<id>` is the device's
**native identifier** (the vmcli label for disk/serial, the named-device string
for USB). `connect`/`disconnect` call `list()`, find the entry whose `id` matches,
read its `type`, and dispatch to the right backend. `list` becomes a **flat,
uniform** inventory (`{id, type, connected, backing}` per device) covering disk,
serial, and **USB** (sourced from the `.vmx` named-device config — there is no
host-hardware enumeration through vmcli/vmrun). Final surface: `list`, `connect`,
`disconnect`, `mount-iso` (kept, because it rebinds the backing then connects;
`eject` dropped as a duplicate of `disconnect <cdrom-id>`).

## Considered options

- **Explicit `--type` flag** (`connect <id> --type usb`) — no `list` lookup, but
  the user must know and repeat the type; fails the "easy to use" goal.
- **Prefix/heuristic type guess** from the id shape — brittle; USB names are
  free-form and can't be reliably distinguished from labels.
- **Synthesized friendly ids** (`usb0`, `disk1`) — adds a mapping the user must
  learn and we must keep stable, on top of the native ids VMware already documents.
- **Resolve via `list`, raw native id, type auto-derived (chosen)** — one id
  namespace for the user, transparent (the id in `list` is the id you type),
  logic unit-testable in the library.

## Consequences

- `connect`/`disconnect` cost **one extra `list` query** to resolve the type.
  Accepted for the ergonomics.
- **Id resolution is exact-match with hard failure modes:** zero matches → error
  listing valid ids; a collision across types → hard error to disambiguate (no
  priority order). The resolver must never silently pick a device.
- **Breaking API + CLI change.** The public typed methods (`connect_disk`,
  `connect_usb`, …) are removed in favour of private `_connect_*` helpers; the
  old per-type commands disappear; `list`'s shape changes from grouped
  `{disks, serial}` to a flat `devices` array now including USB. README,
  CONTEXT.md, and unit tests must be updated. Consistent with this project's prior
  breaking changes (ADR-0001/0002).
- **Backend stays split by type** (vmcli `ConnectionControl` for disk/serial,
  vmrun `connectNamedDevice` for USB) even though `connectNamedDevice` can connect
  any named device — vmcli provides the `connected` state `list` needs and works
  offline. Converging all dispatch onto `connectNamedDevice` is a logged
  follow-up pending live verification, not part of this change.
- **Unverified-live, must confirm at implementation:** the exact `.vmx` key and
  name string `connectNamedDevice` accepts for USB, and whether USB `connected`
  state is readable from the `.vmx`. This is the one part not confirmable from the
  tools' help text.
