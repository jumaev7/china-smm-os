"""Shared pagination defaults for list endpoints."""
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))
