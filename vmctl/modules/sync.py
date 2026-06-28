"""File sync into a running guest, by composition over the ``sss`` library.

vmctl owns VM resolution; ``sss`` owns SSH file-sync. This module is the seam:
it resolves the running guest's IP and reuses the VM's stored guest credentials
as the SSH login, then hands them to ``sss.connect(...)``. sss never learns what
a VM is -- the dependency points vmctl -> sss (see docs/adr/0003).

The IP is read **once**: a usable guest IP requires the VM to be running with a
DHCP lease already assigned. A suspended VM reports a stale last-known IP and a
powered-off VM has none, so this module refuses anything but a running VM and a
non-empty IP rather than guessing or polling (the caller boots/waits).
"""

from ..exceptions import VMCtlError


class SyncModule:
    """``vm.sync`` -- sync/push into the resolved guest over SSH via sss."""

    def __init__(self, network, power, credentials: dict):
        self._network = network
        self._power = power
        self._credentials = credentials or {}

    # -- target resolution --------------------------------------------------

    def _resolve_host(self) -> str:
        """Return the running guest's live IP, or raise an actionable error.

        Single read, no poll: the VM must be ``on`` (a suspended VM's IP is
        stale, a powered-off VM has none) and must already hold a DHCP lease
        (``network.ip()`` returns ``""`` before one lands).
        """
        state = self._power.state().get("PowerState")
        if state != "on":
            raise VMCtlError(
                f"VM is not running (PowerState={state!r}); start it before sync. "
                "sync reads the live guest IP and will not boot the VM for you."
            )
        ip = self._network.ip().get("ip", "")
        if not ip:
            raise VMCtlError(
                "VM is running but has no guest IP yet (DHCP lease pending or no "
                "VMware Tools); wait for an address, then retry."
            )
        return ip

    # -- credential resolution ----------------------------------------------

    def _resolve_credentials(self, user, password):
        """Resolve the SSH login for this run under the both-or-neither rule.

        Both flags present -> the CLI pair fully replaces the stored creds for
        this run (no field-mixing). Neither -> the VM's stored creds (current
        behavior; may be empty, which keeps keyless publickey/agent auth open).
        Exactly one -> an actionable error before any connect is attempted.
        """
        if (user is None) != (password is None):
            raise VMCtlError(
                "provide both --user and --password, or neither."
            )
        if user is not None:  # both present -> override
            return user, password
        return self._credentials.get("user"), self._credentials.get("password")

    def _connect(self, host: str, project_dir=None, profile=None,
                 log=None, user=None, password=None):
        # Lazy import so vmctl's VM commands work without sss/paramiko installed;
        # only sync/push need it. Wrap sss's error type so vmctl's CLI surface
        # stays uniform (its handlers catch VMCtlError/ValueError).
        try:
            import sss
        except ImportError as e:
            raise VMCtlError(
                "sss is not installed; sync/push require it "
                "(`pip install -e ./sss` from the vmctl repo root)."
            ) from e
        user, password = self._resolve_credentials(user, password)
        # sss.connect opens the SSH connection eagerly (auth happens here), so a
        # bad/absent login surfaces now. Rewrap a password-less auth failure to
        # name the real fix instead of the opaque `None@<ip> ... failed` message;
        # keyless auth that succeeds is untouched, other SssErrors keep wrapping.
        try:
            session = sss.connect(
                host=host,
                user=user,
                password=password,
                project_dir=project_dir,
                profile=profile,
                log=log,
            )
        except sss.SssError as e:
            if password is None and "Authentication failed" in str(e):
                raise VMCtlError(
                    f"SSH authentication to {host} failed and no credentials "
                    "were available. Register them with `vmctl auth set`, or "
                    "pass --user and --password to this command."
                ) from e
            raise VMCtlError(str(e)) from e
        return sss, session

    # -- operations ---------------------------------------------------------

    def run(self, sync_optional: bool = False, project_dir=None,
            profile=None, log=None,
            user=None, password=None) -> dict:
        """Full profile lifecycle (pre_sync -> sync -> post_sync) into the guest.

        ``project_dir`` both auto-selects the profile by its git remote and roots
        the profile's relative source paths (ADR-0005); the ``profile`` kwarg is
        an explicit-injection seam used by tests. Build-config/arch substitution
        comes from the profile's own
        ``variables`` in ``~/.sss/config.json`` -- vmctl passes no extra vars.

        ``user``/``password`` are an optional inline credential override (the
        both-or-neither rule lives in ``_connect``); they are runtime-only and
        never persisted.
        """
        host = self._resolve_host()
        sss, session = self._connect(
            host, project_dir=project_dir, profile=profile,
            log=log, user=user, password=password,
        )
        try:
            with session as s:
                if s.profile is None:
                    raise VMCtlError(
                        "No sss sync profile resolved for this project "
                        "(configure ~/.sss/config.json)."
                    )
                return s.run_lifecycle(sync_optional=sync_optional)
        except sss.SssError as e:
            raise VMCtlError(str(e)) from e

    def push(self, source: str, dest: str, project_dir=None, log=None,
             user=None, password=None) -> dict:
        """Ad-hoc, profile-less transfer of ``source`` to remote dir ``dest``.

        ``user``/``password`` are the same optional inline credential override
        as ``run`` (both-or-neither, runtime-only).
        """
        host = self._resolve_host()
        sss, session = self._connect(host, project_dir=project_dir, log=log,
                                     user=user, password=password)
        try:
            with session as s:
                return s.sync.path(source, dest)
        except sss.SssError as e:
            raise VMCtlError(str(e)) from e
