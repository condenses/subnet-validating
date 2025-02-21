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
    last_n_logs: int = 10,
) -> None:
    """
    Watch logs from Redis either for a specific forward_uuid or all recent logs.

    Args:
        redis_client: Redis client instance
        forward_uuid: Specific forward UUID to watch, if None watch all
        follow: If True, continuously watch for new logs
        last_minutes: Show logs from the last N minutes when watching all logs
        last_n_logs: Number of most recent logs to show when following
    """
    while True:
        if forward_uuid:
            # Get logs for specific forward UUID
            logs = await redis_client.hgetall(f"log:{forward_uuid}")
            if logs:
                print(f"\n=== Logs for forward_uuid: {forward_uuid} ===")
                # Sort logs by timestamp and get last N logs
                sorted_logs = sorted(
                    [(datetime.fromisoformat(ts.decode()), msg.decode()) 
                     for ts, msg in logs.items()
                    ],
                    key=lambda x: x[0],
                )[-last_n_logs:]
                for timestamp, message in sorted_logs:
                    print(f"{timestamp.isoformat()}: {message}")
            else:
                print(f"No logs found for forward_uuid: {forward_uuid}")

        else:
            # Get all recent log keys
            all_logs = []
            cutoff_time = datetime.now() - timedelta(minutes=last_minutes)
            async for key in redis_client.scan_iter("log:*"):
                key_str = key.decode()
                logs = await redis_client.hgetall(key_str)
                if logs:
                    for ts_bytes, msg_bytes in logs.items():
                        timestamp = datetime.fromisoformat(ts_bytes.decode())
                        if timestamp >= cutoff_time:
                            message = msg_bytes.decode()
                            all_logs.append((timestamp, key_str, message))
            
            if all_logs:
                # Sort all logs by timestamp and get last N logs
                sorted_logs = sorted(all_logs, key=lambda x: x[0])[-last_n_logs:]
                print("\n=== Recent Logs ===")
                for timestamp, key_str, message in sorted_logs:
                    print(f"{timestamp.isoformat()} [{key_str}]: {message}")

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
    parser.add_argument(
        "--last-n", "-n", type=int, default=10, 
        help="Number of most recent logs to show when following"
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
            last_n_logs=args.last_n,
        )
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
