from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.live import Live
from collections import deque
import time
import asyncio
from redis.asyncio import Redis


class ForwardLog:
    def __init__(self, max_columns=4, redis: Redis = None):
        self.console = Console()
        self.columns_data = deque(maxlen=max_columns)
        self.live = Live(console=self.console, refresh_per_second=4)
        self.redis = redis

    async def add_log(self, synapse_id: str, message: str):
        # Store log in Redis
        await self.redis.lpush(f"logs:{synapse_id}", message)

        # Update local display data
        column_found = False
        for column in self.columns_data:
            if column["id"] == synapse_id:
                column["logs"] = await self.redis.lrange(f"logs:{synapse_id}", 0, -1)
                column_found = True
                break

        if not column_found:
            self.columns_data.append(
                {
                    "id": synapse_id,
                    "logs": await self.redis.lrange(f"logs:{synapse_id}", 0, -1),
                    "start_time": time.time(),
                }
            )
        self.live.update(self.render())

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        await asyncio.sleep(duration)
        # Remove last log from Redis
        await self.redis.rpop(f"logs:{forward_uuid}")

        # Update local display
        for column in self.columns_data:
            if column["id"] == forward_uuid:
                column["logs"] = await self.redis.lrange(f"logs:{forward_uuid}", 0, -1)
                break

    def render(self):
        panels = []
        for column in self.columns_data:
            elapsed = time.time() - column["start_time"]
            content = "\n".join(column["logs"])
            panels.append(
                Panel(
                    content,
                    title=f"[bold blue]Forward {column['id']}[/] ({elapsed:.1f}s)",
                    width=40,
                )
            )
        return Columns(panels)

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.live.stop()
