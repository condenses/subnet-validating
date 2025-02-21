from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.live import Live
import time
import asyncio
import json
from redis.asyncio import Redis


class ForwardLog:
    def __init__(self, redis_client: Redis, max_columns=4, ttl=300):
        self.console = Console()
        self.redis = redis_client
        self.max_columns = max_columns
        self.ttl = ttl  # TTL for log entries (5 minutes default)
        self.live = Live(console=self.console, refresh_per_second=4)
        # Add special key for set_weights
        self.set_weights_key = "forward_log:set_weights"

    async def add_log(self, synapse_id: str, message: str):
        # Get existing logs or create new entry
        redis_key = f"forward_log:{synapse_id}"
        log_data = await self.redis.get(redis_key)

        if log_data:
            column = json.loads(log_data)
        else:
            column = {"id": synapse_id, "logs": [], "start_time": time.time()}

        column["logs"].append(message)

        # Store updated logs with TTL
        await self.redis.set(redis_key, json.dumps(column), ex=self.ttl)

        self.live.update(await self.render())

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        await asyncio.sleep(duration)
        await self.redis.delete(f"forward_log:{forward_uuid}")

    async def render(self):
        panels = []
        # Always get set_weights log first
        set_weights_data = await self.redis.get(self.set_weights_key)
        if set_weights_data:
            column = json.loads(set_weights_data)
            elapsed = time.time() - column["start_time"]
            content = "\n".join(column["logs"])
            panels.append(
                Panel(
                    content,
                    title=f"[bold green]Set Weights[/] ({elapsed:.1f}s)",
                    width=40,
                )
            )

        # Get all active log keys except set_weights
        keys = await self.redis.keys("forward_log:*")
        keys = [k for k in keys if k != self.set_weights_key]
        keys = sorted(keys)[
            -(self.max_columns - 1) :
        ]  # Keep one less to account for set_weights panel

        for key in keys:
            log_data = await self.redis.get(key)
            if log_data:
                column = json.loads(log_data)
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

    async def __aenter__(self):
        self.live.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.live.stop()
