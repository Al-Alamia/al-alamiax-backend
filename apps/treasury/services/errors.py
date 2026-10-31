class TreasuryError(Exception):
    def __init__(self, type, message, errors=None):
        super().__init__(message)
        self.type = type
        self.message = message
        self.errors = errors or []

    @property
    def status(self):
        return {"forbidden": 403, "not_found": 404}.get(self.type, 400)
