class VMCtlError(Exception):
    def __init__(self, message: str, returncode: int = None, stderr: str = None):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr
