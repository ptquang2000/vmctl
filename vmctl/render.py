"""Pure ``dict -> str`` rendering for the CLI (ADR-0007).

The library returns native dicts (the JSON-native programmatic contract); the CLI
renders human-readable, docker/git-flavored text. Every function here is a pure
transform with **zero Click imports**, so output is unit-tested as plain strings
(the testable-without-Click pattern used throughout the codebase). ``cli.py``
calls these then ``click.echo``s the result.

Three shapes:

- **Collections** -> aligned column tables (``ps``, ``snapshot log``,
  ``network ls``, ``peripheral ls``, ``shares ls``, and the ``inspect`` sub-tables).
  Booleans render ``yes``/``no``; an unknown/``None`` value renders ``-``.
  An empty collection renders the header row only.
- **Scalar value-reads** (``network ip``, ``clipboard pull``) -> the bare value,
  nothing else, so they stay pipeable.
- **Mutations** -> a terse confirmation line synthesized from a verb + the
  resolved VM name (library mutation returns are contentless ``{"success": True}``).

Two fields below are guessed from the .vmx and the docker/git conventions rather
than pinned against live vmcli JSON (flagged "verify live" in ADR-0007): the
``snapshot log`` current-marker (driven by ``currentUID``) and the
``Ethernet query`` column names. Both read defensively with ``.get`` and tolerate
alternate key spellings; columns adjust if the live fields differ.
"""

# Gap between table columns (docker-style).
_GAP = "   "


def _yn(value) -> str:
    """Render a tri-state boolean: ``yes``/``no``, or ``-`` for unknown/None."""
    if value is None:
        return "-"
    return "yes" if value else "no"


def _table(headers, rows) -> str:
    """Render an aligned column table. Empty ``rows`` -> the header row only.

    Each column is padded to the widest cell (header included); the final column
    is not padded, and trailing whitespace is stripped per line.
    """
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    lines = []
    for row in [headers] + rows:
        cells = [str(c) for c in row]
        padded = [
            cell.ljust(widths[i]) if i < len(cells) - 1 else cell
            for i, cell in enumerate(cells)
        ]
        lines.append(_GAP.join(padded).rstrip())
    return "\n".join(lines)


def _indent(text: str, spaces: int = 2) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.split("\n"))


# --------------------------------------------------------------------------- #
# collections -> tables                                                        #
# --------------------------------------------------------------------------- #


def ps(rows) -> str:
    """``ps`` -> docker-style ``NAME STATUS`` table.

    ``rows`` is the reshaped ``[{"name", "status"}, ...]`` from the CLI.
    """
    return _table(["NAME", "STATUS"],
                  [[r["name"], r["status"]] for r in rows])


def snapshot_log(data: dict) -> str:
    """``snapshot log`` -> git-log-ish table: a ``*`` current-marker, the
    snapshot name, and its description (when the query carries one)."""
    current = data.get("currentUID")
    rows = []
    for snap in data.get("snapshots", []):
        marker = "*" if snap.get("uid") == current else ""
        rows.append([
            marker,
            snap.get("displayName", ""),
            snap.get("description", "") or "",
        ])
    return _table(["", "NAME", "DESCRIPTION"], rows)


def _eth_devices(data: dict) -> list:
    """Pull the adapter list from an ``Ethernet query`` dict, tolerating either a
    ``devices`` or ``ethernet`` container (verify-live key)."""
    return data.get("devices") or data.get("ethernet") or []


def _eth_connected(dev: dict):
    """Best-effort connected state for an adapter across key spellings."""
    if "connectionStatus" in dev:
        return dev["connectionStatus"] == "connected"
    for key in ("connected", "startConnected"):
        if key in dev:
            return bool(dev[key])
    return None


def network_ls(data: dict) -> str:
    """``network ls`` -> ``LABEL TYPE NETWORK CONNECTED`` table of adapter config."""
    rows = []
    for dev in _eth_devices(data):
        rows.append([
            dev.get("label") or dev.get("name", ""),
            dev.get("connectionType") or dev.get("type", ""),
            dev.get("networkName") or dev.get("network", "") or "",
            _yn(_eth_connected(dev)),
        ])
    return _table(["LABEL", "TYPE", "NETWORK", "CONNECTED"], rows)


def network_ip(data: dict) -> str:
    """``network ip`` -> the bare IP (empty string -> blank line, for scripts)."""
    return data.get("ip", "")


def peripheral_ls(data: dict) -> str:
    """``peripheral ls`` -> docker-style ``ID TYPE CONNECTED BACKING`` table."""
    rows = []
    for dev in data.get("devices", []):
        rows.append([
            dev.get("id", ""),
            dev.get("type", ""),
            _yn(dev.get("connected")),
            dev.get("backing") or "-",
        ])
    return _table(["ID", "TYPE", "CONNECTED", "BACKING"], rows)


def shares_ls(data: dict) -> str:
    """``shares ls`` -> ``LABEL HOST PATH GUEST NAME WRITABLE ENABLED`` table."""
    rows = []
    for f in data.get("folders", []):
        write = f.get("writeAccess")
        if isinstance(write, str):
            write = write.upper() == "TRUE"
        enabled = f.get("enabled")
        if isinstance(enabled, str):
            enabled = enabled.upper() == "TRUE"
        rows.append([
            f.get("label", ""),
            f.get("hostPath", "") or "",
            f.get("guestName", "") or "",
            _yn(write),
            _yn(enabled),
        ])
    return _table(["LABEL", "HOST PATH", "GUEST NAME", "WRITABLE", "ENABLED"], rows)


def clipboard_pull(data: dict) -> str:
    """``clipboard pull`` -> the bare guest clipboard text."""
    return data.get("text", "")


# --------------------------------------------------------------------------- #
# inspect -> curated summary                                                   #
# --------------------------------------------------------------------------- #


def _kv(label: str, value, width: int) -> str:
    return f"  {(label + ':').ljust(width)} {value}"


def _disk_table(disk: dict) -> str:
    """Reshape a raw ``Disk query`` dict into the peripheral-style id/type/
    connected/backing table (cdrom vs disk derived from the backing)."""
    rows = []
    for group in ("cdroms", "disks", "scsis"):
        for e in disk.get(group, []):
            dtype = "cdrom" if e.get("backingType") == "cdrom_image" else "disk"
            status = e.get("connectionStatus")
            connected = (status == "connected") if status is not None else True
            rows.append([
                e.get("label", ""),
                dtype,
                _yn(connected),
                e.get("backingPathName") or "-",
            ])
    return _table(["ID", "TYPE", "CONNECTED", "BACKING"], rows)


def _tools_lines(tools: dict) -> list:
    """A couple of curated Tools facts, defensive across key spellings."""
    lines = []
    for label, keys in (
        ("running", ("toolsRunningStatus", "runningStatus", "running")),
        ("version", ("toolsVersion", "version")),
        ("status", ("toolsVersionStatus", "versionStatus")),
    ):
        for k in keys:
            if k in tools:
                lines.append(f"{label}: {tools[k]}")
                break
    return lines


def inspect(data: dict, vm_name: str) -> str:
    """``inspect`` -> a curated human summary: a power/identity header plus the
    snapshot/disk/network/tools tables. The exhaustive structured dump stays in
    the library (``vm.inspect.inspect()`` + ``parse_vmx()``)."""
    out = [vm_name]

    power = data.get("power")
    state = power.get("PowerState", "?") if isinstance(power, dict) else "?"
    config = data.get("config")
    guest_os = config.get("guestOS", "") if isinstance(config, dict) else ""
    width = len("guest OS:")
    out.append(_kv("power", state, width))
    if guest_os:
        out.append(_kv("guest OS", guest_os, width))

    snaps = data.get("snapshots")
    if isinstance(snaps, dict) and snaps.get("snapshots"):
        out += ["", "snapshots", _indent(snapshot_log(snaps))]

    disks = data.get("disks")
    if isinstance(disks, dict) and any(
        disks.get(g) for g in ("cdroms", "disks", "scsis")
    ):
        out += ["", "disks", _indent(_disk_table(disks))]

    eth = data.get("ethernet")
    if isinstance(eth, dict) and _eth_devices(eth):
        out += ["", "network", _indent(network_ls(eth))]

    tools = data.get("tools")
    if isinstance(tools, dict) and "error" not in tools:
        lines = _tools_lines(tools)
        if lines:
            out += ["", "tools"] + [f"  {line}" for line in lines]

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# mutations -> synthesized confirmation lines                                  #
# --------------------------------------------------------------------------- #


def confirm(verb: str, vm: str) -> str:
    """A lifecycle confirmation: ``<verb> <vm>`` (e.g. ``started windows-10-x64``)."""
    return f"{verb} {vm}"


def cloned(vm: str, dest: str) -> str:
    return f"cloned {vm} -> {dest}"


def exec_launched(vm: str) -> str:
    """``exec`` -> ``launched on <vm>`` (vmcli ``Guest run`` returns no stdout)."""
    return f"launched on {vm}"


def copied(src: str, dst: str) -> str:
    return f"copied {src} -> {dst}"


def pushed(src: str, dst: str) -> str:
    return f"pushed {src} -> {dst}"


def synced(vm: str) -> str:
    return f"synced {vm}"


def auth_set(name: str) -> str:
    return f"credentials set for {name}"


def snapshot_committed(vm: str, snap: str) -> str:
    return f"committed {snap} on {vm}"


def snapshot_reset(vm: str, snap: str) -> str:
    return f"reset {vm} to {snap}"


def snapshot_removed(vm: str, snap: str) -> str:
    return f"removed {snap} from {vm}"


def network_connected(vm: str, label: str) -> str:
    return f"connected {label} on {vm}"


def network_disconnected(vm: str, label: str) -> str:
    return f"disconnected {label} on {vm}"


def network_type_set(vm: str, label: str, type_: str) -> str:
    return f"set {label} type to {type_} on {vm}"


def network_name_set(vm: str, label: str, network_name: str) -> str:
    return f"set {label} network to {network_name} on {vm}"


def peripheral_connected(vm: str, device_id: str) -> str:
    return f"connected {device_id} on {vm}"


def peripheral_disconnected(vm: str, device_id: str) -> str:
    return f"disconnected {device_id} on {vm}"


def iso_mounted(vm: str, label: str, iso: str) -> str:
    return f"mounted {iso} on {label} of {vm}"


def shares_added(vm: str, label: str, host_path: str) -> str:
    return f"added {label} -> {host_path} on {vm}"


def shares_removed(vm: str, label: str) -> str:
    return f"removed {label} from {vm}"


def shares_updated(vm: str, label: str) -> str:
    return f"updated {label} on {vm}"


def clipboard_pushed(vm: str) -> str:
    return f"clipboard set on {vm}"
