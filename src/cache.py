import logging
from functools import cache

import redis.asyncio as redis

from src.config import settings as settings

log = logging.getLogger(__name__)


@cache
def get_redis() -> redis.Redis | None:
    """Un client per processo, oppure None se la cache e disattivata."""
    if not settings.redis_url:
        return None
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )


async def chiudi_redis() -> None:
    """Chiude il client (allo spegnimento)."""
    try:
        client = get_redis()
        if client is not None:
            await client.aclose()
    except Exception:
        log.warning("redis.chiusura_fallita", exc_info=True)
    finally:
        get_redis.cache_clear()
