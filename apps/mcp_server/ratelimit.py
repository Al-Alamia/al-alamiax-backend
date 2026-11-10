from django.core.cache import cache


def hit(key: str, limit: int, window_seconds: int, cost: int = 1) -> bool:
    """Count a hit for key; True while within limit for the window."""
    cache_key = "mcp:rl:" + key
    if cache.add(cache_key, cost, window_seconds):
        return cost <= limit
    try:
        count = cache.incr(cache_key, cost)
    except ValueError:
        cache.set(cache_key, cost, window_seconds)
        count = cost
    return count <= limit
