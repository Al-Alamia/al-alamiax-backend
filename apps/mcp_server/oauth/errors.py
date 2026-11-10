class OAuthError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400):
        super().__init__(error)
        self.error = error
        self.description = description
        self.status = status
