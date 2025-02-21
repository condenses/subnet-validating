from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.live import Live
import time
import asyncio
import json
from redis.asyncio import Redis
from asyncio import Lock


class ForwardLog:
    def __init__(
        self,
        redis_client: Redis,
        max_columns=4,
        ttl=300,
        max_log_entries=10,
        panel_width=40,
    ):
        self.console = Console()
        self.redis = redis_client
        self.max_columns = max_columns
        self.ttl = ttl
        self.max_log_entries = max_log_entries
        self.panel_width = panel_width
        self.live = Live(console=self.console, refresh_per_second=4, auto_refresh=False)
        self.set_weights_key = "forward_log:set_weights"
        self.lock = Lock()

    async def add_log(self, synapse_id: str, message: str):
        async with self.lock:
            redis_key = f"forward_log:{synapse_id}"
            try:
                log_data = await self.redis.get(redis_key)
                column = (
                    json.loads(log_data)
                    if log_data
                    else {"id": synapse_id, "logs": [], "start_time": time.time()}
                )

                column["logs"].append(message)
                column["logs"] = column["logs"][-self.max_log_entries :]

                # Use pipeline for atomic operations
                async with self.redis.pipeline() as pipe:
                    pipe.set(redis_key, json.dumps(column), ex=self.ttl)
                    if not log_data:  # New entry, add to tracking set
                        pipe.sadd("forward_log:keys", redis_key)
                    await pipe.execute()

                self.live.update(await self.render())
            except Exception as e:
                self.console.print(f"[red]Error updating log: {e}[/]")

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        await asyncio.sleep(duration)
        async with self.lock:
            try:
                key = f"forward_log:{forward_uuid}"
                await self.redis.srem("forward_log:keys", key)
                await self.redis.delete(key)
                self.live.update(await self.render())
            except Exception as e:
                self.console.print(f"[red]Error removing log: {e}[/]")

    async def render(self):
        try:
            panels = []
            # Handle set_weights separately
            set_weights_data = await self.redis.get(self.set_weights_key)
            if set_weights_data:
                panels.append(
                    self._create_panel(
                        json.loads(set_weights_data), "green", "Set Weights"
                    )
                )

            # Get active keys using tracking set instead of KEYS
            log_keys = await self.redis.smembers("forward_log:keys")
            log_keys = [key for key in log_keys if key != self.set_weights_key]

            values = await self.redis.mget(log_keys)
            columns = []
            for key, value in zip(log_keys, values):
                if value:
                    column = json.loads(value)
                    column["redis_key"] = key  # Store key for expiration check
                    columns.append(column)

            # Filter expired entries and sort by recency
            columns = [c for c in columns if await self.redis.exists(c["redis_key"])]
            columns.sort(key=lambda x: x["start_time"], reverse=True)

            # Add most recent columns
            for column in columns[: self.max_columns - len(panels)]:
                panels.append(
                    self._create_panel(column, "blue", f"Forward {column['id']}")
                )

            return Columns(panels, expand=True)
        except Exception as e:
            self.console.print(f"[red]Error rendering logs: {e}[/]")
            return Columns([])

    def _create_panel(self, column, color, title_prefix):
        elapsed = time.time() - column["start_time"]
        content = "\n".join(column["logs"][-self.max_log_entries :])
        title = f"[bold {color}]{title_prefix}[/] ({elapsed:.1f}s)"
        return Panel(
            content,
            title=title,
            width=self.panel_width,
            style=color,
            subtitle_align="right",
        )
