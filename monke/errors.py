class Rejected(Exception):
    """An input the engine refuses. It carries a text key and variables, never prose (TXT-2): the adapter turns it
    into a message with the text system. The text is safe to show to the player and never names a role (QOL-11)."""

    def __init__(self, key: str, **vars):
        super().__init__(key)
        self.key, self.vars = key, vars

    @property
    def reason(self) -> str:
        """What the command log stores: the key (the archive turns it into words)."""
        return self.key
