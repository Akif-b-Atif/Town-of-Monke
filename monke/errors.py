class Rejected(Exception):
    """An input the engine refuses. `reason` is safe to show to the player (never leaks roles)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
