from typing import List, Dict, Any
from redis.asyncio import Redis
from datetime import datetime, timedelta


class RedisManager:
    def __init__(self, redis_client: Redis):
        # Decode responses is enabled by default
        self.redis = redis_client
        self.log_ttl = 3600  # 1 hour TTL for logs

    async def flush_db(self):
        await self.redis.flushdb()

    async def get_scored_counter(self) -> Dict[int, int]:
        """Get counter of scored UIDs"""
        scored_counter = {}
        async for key in self.redis.scan_iter("scored_uid:*"):
            uid = int(key.decode().split(":")[1])
            count = await self.redis.get(key)
            scored_counter[uid] = int(count)
        return scored_counter

    async def update_scoring_records(self, uids: List[int], config: Any) -> None:
        """Update scoring records in Redis"""
        pipe = self.redis.pipeline()
        for uid in uids:
            key = f"{config.validating.scoring_rate.redis_key}:{uid}"
            pipe.incr(key)
            pipe.expire(key, config.validating.scoring_rate.interval)
        await pipe.execute()

    async def add_log(self, forward_uuid: str, message: str) -> None:
        """Add a log message to Redis"""
        timestamp = datetime.now().isoformat()
        log_key = f"log:{forward_uuid}"
        
        # Store log entry as a hash with timestamp and message
        await self.redis.hset(log_key, timestamp, message)
        await self.redis.expire(log_key, self.log_ttl)

    async def get_logs(self, forward_uuid: str) -> List[tuple[str, str]]:
        """Get all logs for a specific forward UUID"""
        log_key = f"log:{forward_uuid}"
        logs = await self.redis.hgetall(log_key)
        return [(ts.decode(), msg.decode()) for ts, msg in logs.items()]
