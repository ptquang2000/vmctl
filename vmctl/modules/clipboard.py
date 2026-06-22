import os
import tempfile
import time
from typing import Callable, Optional

# vmcli "Guest run" accepts the program plus a SINGLE programArgs token (verified
# live: a second trailing token errors "Invalid/unrecognized argument"). So all
# Windows guest work is funnelled through cmd.exe with one combined "/c ..." token
# and cmd re-parses it. Two further live findings shape the recipe below:
#   * interactive=True breaks output capture for the clipboard read (the program
#     lands on a desktop whose stdout we don't inherit); interactive=False both
#     captures stdout AND round-trips the clipboard consistently.
#   * vmcli's synchronous wait returns before a nested cmd->powershell grandchild
#     finishes, so the clipboard *read* is fired with --noWait and its artifact
#     file is polled until it materialises.
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
        """Run a Windows command line as a single cmd.exe ``/c`` token."""
        self._run_guest("cmd.exe", f"/c {command}", no_wait=no_wait, interactive=False)

    def push_text(self, text: str) -> dict:
        is_win = self._is_windows_guest()
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
            # clip.exe loads stdin into the clipboard. It is a direct child of
            # cmd, so a synchronous (waited) run reliably completes before we
            # return -- guaranteeing the clipboard is set before any pull.
            self._run_cmd(f"clip < {guest_clip_path}", no_wait=False)
        else:
            self._run_guest("bash", "-c", f"xclip -selection clipboard < {guest_clip_path}")
        return {"success": True}

    def pull_text(self) -> dict:
        is_win = self._is_windows_guest()
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
