import httpx
from loguru import logger
import os
import asyncio
from redis.asyncio import Redis
from .config import CONFIG
import time


async def get_unstake_events(netuid: int):
    timestamp_start = int(time.time()) - int(24 * 60 * 60)
    url = f"https://api.taostats.io/api/delegation/v1"
    params = {
        "netuid": netuid,
        "page": 1,
        "limit": 200,
        "action": "undelegate",
        "timestamp_start": timestamp_start,
    }
    headers = {"Authorization": CONFIG.taostats_api_key}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
    data = response.json()["data"]
    logger.info(f"Received {len(data)} unstake events from netuid {netuid}")
    events = []
    for event in data:
        events.append(
            {
                "extrinsic_id": event["extrinsic_id"],
                "ss58_address": event["nominator"]["ss58"],
            }
        )
    return events


async def get_metagraph(netuid: int) -> dict[str, int]:
    url = f"https://api.taostats.io/api/metagraph/latest/v1"
    params = {"netuid": netuid, "limit": 256}
    headers = {"Authorization": CONFIG.taostats_api_key}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
    data = response.json()["data"]
    hotkey_to_uid = {item["hotkey"]["ss58"]: item["uid"] for item in data}
    logger.info(f"Received {len(hotkey_to_uid)} hotkeys from netuid {netuid}")
    return hotkey_to_uid


class UnstakeProcessor:
    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client
        self.recent_events = []
        self.processed_events_key = "unstake:processed_events"
        self.hotkey_to_uid = {}

    async def auto_sync_events(self, netuid: int, interval: int = 1200):
        while True:
            try:
                events = await get_unstake_events(netuid)
                self.recent_events = events
                logger.info(f"Synced {len(events)} unstake events from netuid {netuid}")
                self.hotkey_to_uid = await get_metagraph(netuid)
            except Exception as e:
                logger.error(f"Error syncing unstake events: {e}")
            await asyncio.sleep(interval)

    async def get_buy_uids(self) -> list[int]:
        """Return events that are not in the processed_events set and push them to the processed_events set"""
        processed_events = await self.redis_client.smembers(self.processed_events_key)
        processed_events = {event.decode() for event in processed_events}
        new_events = [
            event
            for event in self.recent_events
            if event["extrinsic_id"] not in processed_events
        ]
        logger.info(f"Found {len(new_events)} new unstake events")
        if new_events:
            # Add new event IDs to the Redis set
            await self.redis_client.sadd(
                self.processed_events_key,
                *[event["extrinsic_id"] for event in new_events],
            )
            logger.info(
                f"Added {len(new_events)} new unstake events to processed_events"
            )

        return [
            self.hotkey_to_uid[event["ss58_address"]]
            for event in new_events
            if event["ss58_address"] in self.hotkey_to_uid
        ]

    async def clear_processed_events(self):
        await self.redis_client.delete(self.processed_events_key)


async def main():
    # This is just for testing
    from redis.asyncio import Redis

    redis_client = Redis(host="localhost", port=6379, db=0)

    processor = UnstakeProcessor(redis_client)
    await processor.clear_processed_events()
    asyncio.create_task(processor.auto_sync_events(47))
    while True:
        uids = await processor.get_buy_uids()
        print(f"New uids to buy: {uids}")
        await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
