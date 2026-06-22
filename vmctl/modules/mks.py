class MKSModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def query(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "MKS", "query", "-f", "json")

    def screenshot(self, output_path: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "MKS", "captureScreenshot", output_path)

    def send_key(self, hidcode: int, modifier: int) -> dict:
        return self._r.run_vmcli_action(
            self._vmx, "MKS", "sendKeyEvent", str(hidcode), str(modifier)
        )

    def send_key_sequence(self, sequence: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "MKS", "sendKeySequence", sequence)

    def set_resolution(self, width: int, height: int) -> dict:
        return self._r.run_vmcli_action(
            self._vmx, "MKS", "SetGuestResolution", str(width), str(height)
        )

    def set_num_displays(self, n: int) -> dict:
        return self._r.run_vmcli_action(self._vmx, "MKS", "SetNumDisplays", str(n))
