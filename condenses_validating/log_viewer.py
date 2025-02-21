import asyncio
from datetime import datetime
from typing import List, Tuple
from collections import deque
import redis.asyncio as aioredis
from rich.console import Console
from rich.table import Table


class LogViewer:
    """A simple log viewer using rich for terminal output."""

    def __init__(self):
        self.console = Console()
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.set_weights_logs = deque(maxlen=6)
        self.regular_logs = deque(maxlen=6)

    async def fetch_logs(self) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """Retrieve log data from Redis."""
        keys = []
        self.set_weights_logs.clear()
        self.regular_logs.clear()

        async for key in self.redis.scan_iter("log:*"):
            parts = key.split(":")
            if len(parts) < 2:
                continue
            uuid = parts[1]
            logs_dict = await self.redis.hgetall(key)
            logs = sorted(logs_dict.items(), key=lambda x: x[0])

            if "set_weights" in uuid:
                self.set_weights_logs.append((uuid, logs))
            else:
                self.regular_logs.append((uuid, logs))

        return list(self.regular_logs)

    def display_logs(self):
        """Display logs using rich."""
        table = Table(title="Log Viewer")

        table.add_column("UUID", justify="right", style="cyan", no_wrap=True)
        table.add_column("Timestamp", style="magenta")
        table.add_column("Message", style="green")

        for uuid, logs in self.set_weights_logs:
            for timestamp, message in logs:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%H:%M:%S")
                except Exception:
                    formatted_time = timestamp
                table.add_row(uuid[:8], formatted_time, message)

        for uuid, logs in self.regular_logs:
            for timestamp, message in logs:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%H:%M:%S")
                except Exception:
                    formatted_time = timestamp
                table.add_row(uuid[:8], formatted_time, message)

        self.console.print(table)

    async def run(self):
        """Main loop to fetch and display logs."""
        while True:
            await self.fetch_logs()
            self.console.clear()
            self.display_logs()
            await asyncio.sleep(2)

    async def close(self):
        """Close the Redis connection."""
        await self.redis.close()


if __name__ == "__main__":
    viewer = LogViewer()
    try:
        asyncio.run(viewer.run())
    except KeyboardInterrupt:
        asyncio.run(viewer.close())
