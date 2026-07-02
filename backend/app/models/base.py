from datetime import datetime, timezone


def agora() -> datetime:
    return datetime.now(timezone.utc)
