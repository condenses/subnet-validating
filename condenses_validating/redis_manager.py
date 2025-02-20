from typing import List, Dict, Any
from redis.asyncio import Redis


class RedisManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

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
