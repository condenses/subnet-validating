import asyncio
from redis.asyncio import Redis
from datetime import datetime, timedelta
import argparse
from typing import Optional


async def watch_logs(
    redis_client: Redis,
    forward_uuid: Optional[str] = None,
    follow: bool = False,
    last_minutes: int = 60,
) -> None:
    """
    Watch logs from Redis either for a specific forward_uuid or all recent logs.

    Args:
        redis_client: Redis client instance
        forward_uuid: Specific forward UUID to watch, if None watch all
        follow: If True, continuously watch for new logs
        last_minutes: Show logs from the last N minutes when watching all logs
    """
    while True:
        if forward_uuid:
            # Get logs for specific forward UUID
            logs = await redis_client.hgetall(f"log:{forward_uuid}")
            if logs:
                print(f"\n=== Logs for forward_uuid: {forward_uuid} ===")
                for ts_bytes, msg_bytes in logs.items():
                    timestamp = ts_bytes.decode()
                    message = msg_bytes.decode()
                    print(f"{timestamp}: {message}")
            else:
                print(f"No logs found for forward_uuid: {forward_uuid}")

        else:
            # Get all recent log keys
            cutoff_time = datetime.now() - timedelta(minutes=last_minutes)
            async for key in redis_client.scan_iter("log:*"):
                key_str = key.decode()
                logs = await redis_client.hgetall(key_str)
                if logs:
                    print(f"\n=== Logs for {key_str} ===")
                    for ts_bytes, msg_bytes in sorted(logs.items()):
                        timestamp = datetime.fromisoformat(ts_bytes.decode())
                        if timestamp >= cutoff_time:
                            message = msg_bytes.decode()
                            print(f"{timestamp.isoformat()}: {message}")

        if not follow:
            break

        await asyncio.sleep(1)


async def main():
    parser = argparse.ArgumentParser(description="Redis Log Viewer")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--forward-uuid", help="Specific forward UUID to watch")
    parser.add_argument(
        "--follow", "-f", action="store_true", help="Continuously watch for new logs"
    )
    parser.add_argument(
        "--minutes", "-m", type=int, default=60, help="Show logs from last N minutes"
    )

    args = parser.parse_args()

    redis = Redis(
        host=args.host,
        port=args.port,
        decode_responses=False,  # Keep as bytes for consistent handling
    )

    try:
        await watch_logs(
            redis,
            forward_uuid=args.forward_uuid,
            follow=args.follow,
            last_minutes=args.minutes,
        )
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
