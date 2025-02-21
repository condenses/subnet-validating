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

    async def add_log(self, synapse_id: str, message: str):
        # Get existing logs or create new entry
        redis_key = f"forward_log:{synapse_id}"
        log_data = await self.redis.get(redis_key)
        
        if log_data:
            column = json.loads(log_data)
        else:
            column = {
                "id": synapse_id,
                "logs": [],
                "start_time": time.time()
            }
            
        column["logs"].append(message)
        
        # Store updated logs with TTL
        await self.redis.set(
            redis_key,
            json.dumps(column),
            ex=self.ttl
        )
        
        self.live.update(await self.render())

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        await asyncio.sleep(duration)
        await self.redis.delete(f"forward_log:{forward_uuid}")

    async def render(self):
        panels = []
        # Get all active log keys
        keys = await self.redis.keys("forward_log:*")
        keys = sorted(keys)[-self.max_columns:]  # Keep only most recent logs
        
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

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.live.stop()
