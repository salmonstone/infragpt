import redis
import hashlib
import json
from config import settings

_client = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _question_key(username: str, question: str) -> str:
    digest = hashlib.sha256(f"{username}:{question}".encode()).hexdigest()
    return f"cache:chat:{digest}"


def _rate_key(username: str) -> str:
    return f"rate:{username}"


def get_cached_answer(username: str, question: str):
    try:
        r = get_redis()
        val = r.get(_question_key(username, question))
        return json.loads(val) if val else None
    except Exception:
        return None


def set_cached_answer(username: str, question: str, answer: dict):
    try:
        r = get_redis()
        r.setex(_question_key(username, question), settings.redis_cache_ttl, json.dumps(answer))
    except Exception:
        pass


def check_rate_limit(username: str) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    try:
        r = get_redis()
        key = _rate_key(username)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.rate_limit_window)
        count, _ = pipe.execute()
        return count <= settings.rate_limit_requests
    except Exception:
        return True  # fail open if Redis is down
