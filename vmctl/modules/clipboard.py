import os
import tempfile
import time
from typing import Callable, Optional

from ..exceptions import VMCtlError

# vmcli "Guest run" accepts the program plus a SINGLE programArgs token (verified
# live: a second trailing token errors "Invalid/unrecognized argument"). So all
# Windows guest work is funnelled through cmd.exe with one combined "/c ..." token
# and cmd re-parses it. The clipboard the logged-in user sees lives on the
# interactive desktop's window station (WinSta0\Default); a non-interactive
# "Guest run" lands on a *separate* window station with its own, invisible
# clipboard (ADR-0008). So both halves run --interactive to touch the real one.
# Two further live findings shape the recipe below:
#   * --interactive does not search PATH, so cmd.exe must be an absolute path
#     (bare "cmd.exe" fails with "A file was not found").
#   * vmcli's synchronous wait returns before a nested cmd->powershell grandchild
#     finishes, so the clipboard *read* is fired with --noWait and its artifact
#     file is polled until it materialises.
_CMD_EXE = r"C:\Windows\System32\cmd.exe"
_PULL_POLL_TIMEOUT_S = 25
_PULL_POLL_INTERVAL_S = 2


class ClipboardModule:
    def __init__(
        self,
        vmx_path: str,
        runner,
        credentials: dict,
        guest_os_fn: Optional[Callable[[], str]] = None,
    ):
        self._vmx = vmx_path
        self._r = runner
        self._creds = credentials
        self._guest_os_fn = guest_os_fn or self._query_guest_os

    def _cred_args(self) -> list:
        args = []
        if self._creds.get("user"):
            args += ["--username", self._creds["user"]]
        if self._creds.get("password"):
            args += ["--password", self._creds["password"]]
        return args

    def _query_guest_os(self) -> str:
        from ..runner import _extract_json
        raw = self._r.run_vmcli(self._vmx, "ConfigParams", "query", "-f", "json")
        cfg = _extract_json(raw)
        return cfg.get("guestOS", "")

    def _is_windows_guest(self) -> bool:
        return "windows" in self._guest_os_fn().lower()

    def _copy_to(self, host_path: str, guest_path: str) -> None:
        args = ["Guest", "copyTo"] + self._cred_args() + ["--overwrite", host_path, guest_path]
        self._r.run_vmcli_action(self._vmx, *args)

    def _copy_from(self, guest_path: str, host_path: str) -> None:
        args = ["Guest", "copyFrom"] + self._cred_args() + ["--overwrite", guest_path, host_path]
        self._r.run_vmcli_action(self._vmx, *args)

    def _run_guest(self, program: str, *prog_args: str, no_wait: bool = True, interactive: bool = False) -> None:
        args = ["Guest", "run"] + self._cred_args()
        if no_wait:
            args.append("--noWait")
        if interactive:
            args.append("--interactive")
        args += [program] + list(prog_args)
        self._r.run_vmcli_action(self._vmx, *args)

    def _run_cmd(self, command: str, no_wait: bool = False) -> None:
        """Run a Windows command line as a single cmd.exe ``/c`` token.

        Runs ``--interactive`` (so it touches the logged-in desktop's clipboard,
        not a phantom one) using an absolute cmd path (``--interactive`` does not
        search ``PATH``).
        """
        self._run_guest(_CMD_EXE, f"/c {command}", no_wait=no_wait, interactive=True)

    def _require_interactive_session(self) -> None:
        """Fail loud unless a logged-in desktop session exists to share.

        No interactive desktop = no clipboard to touch. A cold boot at the
        login/lock screen reports ``running=true`` but
        ``GuestCaps.copyPasteGuestVersion=0`` for minutes -- exactly the
        "reports success but does nothing" case. Gate on ``copyPasteGuestVersion``
        (the precise capability this feature depends on), not the broader
        ``guestCapable``. Lives in the module so the library also tells the truth.
        """
        from ..runner import _extract_json
        facts = _extract_json(self._r.run_vmcli(self._vmx, "Tools", "Query", "-f", "json"))
        running = facts.get("running") is True
        copy_paste = facts.get("GuestCaps", {}).get("copyPasteGuestVersion", 0)
        if not (running and copy_paste > 0):
            raise VMCtlError(
                f"no interactive guest session (copyPasteGuestVersion={copy_paste}); "
                "clipboard needs a user logged into the guest desktop -- a VM at "
                "the login/lock screen can't share its clipboard"
            )

    def push_text(self, text: str) -> dict:
        is_win = self._is_windows_guest()
        if is_win:
            self._require_interactive_session()
        guest_clip_path = (
            r"C:\Windows\Temp\vmctl_clip.txt" if is_win else "/tmp/vmctl_clip.txt"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as f:
            f.write(text)
            host_tmp = f.name
        try:
            self._copy_to(host_tmp, guest_clip_path)
        finally:
            os.unlink(host_tmp)

        if is_win:
            # clip.exe loads stdin into the clipboard. Under --interactive it is
            # a direct child of cmd, so a synchronous (waited) run still reliably
            # completes and sets the clipboard before we return (verified live).
            self._run_cmd(f"clip < {guest_clip_path}", no_wait=False)
        else:
            self._run_guest("bash", "-c", f"xclip -selection clipboard < {guest_clip_path}")
        return {"success": True}

    def pull_text(self) -> dict:
        is_win = self._is_windows_guest()
        if is_win:
            self._require_interactive_session()
        guest_out_path = (
            r"C:\Windows\Temp\vmctl_clip_out.txt" if is_win else "/tmp/vmctl_clip_out.txt"
        )
        if is_win:
            # Clear any stale artifact, then read the clipboard via powershell,
            # letting cmd redirect stdout to the file. Fired with --noWait
            # because vmcli does not reliably wait for the nested powershell.
            self._run_cmd(f"del /q {guest_out_path}", no_wait=False)
            self._run_cmd(
                f"powershell -NoProfile -Command Get-Clipboard > {guest_out_path} 2>&1",
                no_wait=True,
            )
            content = self._poll_guest_file(guest_out_path)
        else:
            self._run_guest(
                "bash",
                "-c",
                f"xclip -selection clipboard -o > {guest_out_path}",
                no_wait=False,
            )
            content = self._read_guest_file(guest_out_path) or ""
        return {"text": content}

    def _read_guest_file(self, guest_path: str) -> Optional[str]:
        """Copy a guest file to the host and return its text, or None if absent."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            host_tmp = f.name
        try:
            self._copy_from(guest_path, host_tmp)
            with open(host_tmp, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return None
        finally:
            os.unlink(host_tmp)

    def _poll_guest_file(self, guest_path: str) -> str:
        """Poll a guest artifact until it has content (bounded), then return it."""
        deadline = time.time() + _PULL_POLL_TIMEOUT_S
        while time.time() < deadline:
            content = self._read_guest_file(guest_path)
            if content is not None and content.strip() != "":
                return content
            time.sleep(_PULL_POLL_INTERVAL_S)
        return self._read_guest_file(guest_path) or ""
