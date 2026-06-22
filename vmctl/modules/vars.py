_VALID_NAMESPACES = {"guestVar", "guestEnv", "runtimeConfig"}


class VarsModule:
    def __init__(self, vmx_path: str, runner, credentials: dict = None):
        self._vmx = vmx_path
        self._r = runner
        self._creds = credentials or {}

    def _check_namespace(self, namespace: str) -> None:
        if namespace not in _VALID_NAMESPACES:
            raise ValueError(
                f"Invalid namespace '{namespace}'. Must be one of: {sorted(_VALID_NAMESPACES)}"
            )

    def _guest_auth(self, namespace: str) -> list:
        # The guestEnv namespace reads/writes the live guest's environment, so
        # vmrun rejects it without guest credentials ("Command requires valid
        # user name and password for the guest OS" -- verified live). guestVar
        # and runtimeConfig are VM-state variables and need no guest login.
        if namespace == "guestEnv" and self._creds.get("user"):
            return ["-gu", self._creds["user"], "-gp", self._creds.get("password", "")]
        return []

    def read(self, namespace: str, name: str) -> dict:
        self._check_namespace(namespace)
        args = self._guest_auth(namespace) + ["readVariable", self._vmx, namespace, name]
        raw = self._r.run_vmrun(*args)
        return {"value": raw.strip()}

    def write(self, namespace: str, name: str, value: str) -> dict:
        self._check_namespace(namespace)
        args = self._guest_auth(namespace) + ["writeVariable", self._vmx, namespace, name, value]
        self._r.run_vmrun(*args)
        return {"success": True}
