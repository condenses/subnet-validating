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

    async def get_scored_counter(self, uids: List[int]) -> Dict[int, int]:
        """Get counter of scored UIDs"""
        scored_counter = {}
        # Only scan for the specific UIDs in the provided list
        for uid in uids:
            key = f"scored_uid:{uid}"
            count = await self.redis.get(key)
            if count is not None:
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
        # Since decode_responses=True, the values are already decoded
        return [(ts, msg) for ts, msg in logs.items()]

    async def get_latest_logs(self, n: int = 5) -> list[tuple[str, str, str]]:
        """Get the latest n logs across all UUIDs."""
        all_logs = []
        async for key in self.redis.scan_iter("log:*"):
            uuid = key.split(":")[1]
            logs = await self.get_logs(uuid)
            for timestamp, message in logs:
                all_logs.append((uuid, timestamp, message))

        # Sort by timestamp and get the latest n
        all_logs.sort(key=lambda x: datetime.fromisoformat(x[1]), reverse=True)
        return all_logs[:n]

    async def search_logs(self, search_term: str) -> list[tuple[str, str, str]]:
        """Search for logs containing the given string."""
        matching_logs = []
        async for key in self.redis.scan_iter("log:*"):
            uuid = key.split(":")[1]
            logs = await self.get_logs(uuid)
            for timestamp, message in logs:
                if search_term.lower() in message.lower():
                    matching_logs.append((uuid, timestamp, message))

        # Sort by timestamp, most recent first
        matching_logs.sort(key=lambda x: datetime.fromisoformat(x[1]), reverse=True)
        return matching_logs
