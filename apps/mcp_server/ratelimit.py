from django.core.cache import cache


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Count a hit for key; True while within limit for the window."""
    cache_key = "mcp:rl:" + key
    if cache.add(cache_key, 1, window_seconds):
        return 1 <= limit
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, window_seconds)
        count = 1
    return count <= limit
