import logging

import redis

from app.core.config import settings

logger = logging.getLogger("app.cache")

VERSION_KEY = "catalog:version"


class Cache:
    def __init__(self, url: str | None, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self.client = (
            redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.3, socket_timeout=0.3)
            if url
            else None
        )

    def key(self, *parts: object) -> str | None:
        if self.client is None:
            return None
        try:
            version = self.client.get(VERSION_KEY) or "0"
        except redis.RedisError:
            logger.warning("cache_unavailable", extra={"operation": "version"})
            return None
        return f"catalog:v{version}:" + ":".join(str(part) for part in parts)

    def get(self, key: str | None) -> str | None:
        if self.client is None or key is None:
            return None
        try:
            return self.client.get(key)
        except redis.RedisError:
            logger.warning("cache_unavailable", extra={"operation": "get"})
            return None

    def set(self, key: str | None, value: str) -> None:
        if self.client is None or key is None:
            return
        try:
            self.client.set(key, value, ex=self.ttl_seconds)
        except redis.RedisError:
            logger.warning("cache_unavailable", extra={"operation": "set"})

    def invalidate_catalog(self) -> None:
        if self.client is None:
            return
        try:
            self.client.incr(VERSION_KEY)
        except redis.RedisError:
            logger.warning("cache_unavailable", extra={"operation": "invalidate"})


cache = Cache(settings.redis_url, settings.cache_ttl_seconds)
