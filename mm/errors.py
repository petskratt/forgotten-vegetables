class Halt(Exception):
    """Stop the run. State is already saved; the same command continues."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ConfigError(Exception):
    pass


def annotate(exc: Halt, label: str, posts_saved: int) -> Halt:
    if exc.reason.startswith("Stopped:"):
        return exc
    return Halt(
        f"Stopped: {exc.reason} "
        f"(channel {label}, {posts_saved} posts saved). "
        "Run the same command to continue."
    )
