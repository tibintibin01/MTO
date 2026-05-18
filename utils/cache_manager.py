import time
import json
from typing import Any, Optional, Dict
from utils.secrets_manager import secrets
from utils.logger import mto_logger

class CacheManager:
    """
    Unified Namespaced Distributed Cache Manager.
    Tries connecting to centralized Redis for cloud scalability,
    with an automatic, safe fallback to namespaced local in-memory caching.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self._redis_client = None
        self._memory_cache: Dict[str, Dict[str, tuple]] = {} # {namespace: {key: (value, expire_time)}}
        self._engine = "IN-MEMORY (Local Fallback)"

        # Attempt to initialize Redis Client
        try:
            import redis
            host = secrets.redis_host
            port = secrets.redis_port
            
            # Simple connection pool with short timeout to prevent boot blockages
            self._redis_client = redis.Redis(
                host=host, 
                port=port, 
                db=0, 
                socket_connect_timeout=2.0, 
                socket_timeout=2.0
            )
            # Test connectivity
            self._redis_client.ping()
            self._engine = f"REDIS ({host}:{port})"
            mto_logger.info(f"CacheManager initialized in Distributed Cloud mode using {self._engine}")
        except Exception as e:
            self._redis_client = None
            mto_logger.warning(
                f"CacheManager: Redis distributed cache is offline. Falling back to local Namespaced Memory Cache. Detail: {e}"
            )
            
        self._initialized = True

    @property
    def engine(self) -> str:
        return self._engine

    def get(self, namespace: str, key: str) -> Optional[Any]:
        """Retrieves a cached value, checking TTL limits."""
        if self._redis_client:
            try:
                full_key = f"mto:{namespace}:{key}"
                val = self._redis_client.get(full_key)
                if val is not None:
                    return json.loads(val.decode("utf-8"))
            except Exception as e:
                # Fault tolerance: log warning but continue execution
                mto_logger.warning(f"CacheManager: Redis GET failed for {namespace}:{key}: {e}")
            return None

        # Memory fallback
        ns_dict = self._memory_cache.get(namespace, {})
        if key in ns_dict:
            value, expire_time = ns_dict[key]
            if expire_time is None or expire_time > time.time():
                return value
            # Clean expired item
            del ns_dict[key]
        return None

    def set(self, namespace: str, key: str, value: Any, ttl: int = 60) -> bool:
        """Saves a namespaced item into the active caching engine."""
        if self._redis_client:
            try:
                full_key = f"mto:{namespace}:{key}"
                serialized = json.dumps(value)
                self._redis_client.setex(full_key, ttl, serialized)
                return True
            except Exception as e:
                mto_logger.warning(f"CacheManager: Redis SET failed for {namespace}:{key}: {e}")
                return False

        # Memory fallback
        if namespace not in self._memory_cache:
            self._memory_cache[namespace] = {}
        
        expire_time = time.time() + ttl
        self._memory_cache[namespace][key] = (value, expire_time)
        return True

    def clear(self, namespace: Optional[str] = None) -> bool:
        """Clears cache values (either a specific namespace or globally)."""
        if self._redis_client:
            try:
                pattern = f"mto:{namespace}:*" if namespace else "mto:*"
                keys = self._redis_client.keys(pattern)
                if keys:
                    self._redis_client.delete(*keys)
                mto_logger.info(f"CacheManager: Cleared Redis keys matching pattern: {pattern}")
                return True
            except Exception as e:
                mto_logger.warning(f"CacheManager: Redis delete failed: {e}")
                return False

        # Memory fallback
        if namespace:
            if namespace in self._memory_cache:
                self._memory_cache[namespace].clear()
        else:
            self._memory_cache.clear()
            
        mto_logger.info("CacheManager: In-Memory cache cleared successfully.")
        return True

# Global Instance
cache = CacheManager()
