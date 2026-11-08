class ReportError(Exception):
    def __init__(self, message: str, type: str = "invalid", fields: "dict[str, str] | None" = None):
        super().__init__(message)
        self.message = message
        self.type = type
        self.fields = fields or {}
