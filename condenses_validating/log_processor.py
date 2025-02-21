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
        self.ttl = ttl  # Log expiration time (default: 5 minutes)
        self.live = Live(console=self.console, refresh_per_second=4)
        self.set_weights_key = "forward_log:set_weights"

    async def add_log(self, synapse_id: str, message: str):
        """Adds a log message for a given synapse ID."""
        redis_key = f"forward_log:{synapse_id}"
        log_data = await self.redis.get(redis_key)

        column = (
            json.loads(log_data)
            if log_data
            else {"id": synapse_id, "logs": [], "start_time": time.time()}
        )

        column["logs"].append(message)
        await self.redis.set(redis_key, json.dumps(column), ex=self.ttl)

        # Update UI only if live display is running
        if self.live.is_started:
            self.live.update(await self.render())

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        """Removes a log entry after a delay."""
        await asyncio.sleep(duration)
        await self.redis.delete(f"forward_log:{forward_uuid}")

    async def render(self):
        """Generates the Rich UI representation of the logs."""
        panels = []

        # Retrieve logs from Redis
        keys = await self.redis.keys("forward_log:*")
        if not keys:
            return Columns([])

        logs = await self.redis.mget(keys)
        log_entries = {key: json.loads(log) for key, log in zip(keys, logs) if log}

        # Always prioritize set_weights log
        set_weights_log = log_entries.pop(self.set_weights_key, None)
        if set_weights_log:
            elapsed = time.time() - set_weights_log["start_time"]
            panels.append(
                Panel(
                    "\n".join(set_weights_log["logs"]),
                    title=f"[bold green]Set Weights[/] ({elapsed:.1f}s)",
                    width=40,
                )
            )

        # Sort logs by time and keep the latest ones
        sorted_logs = sorted(
            log_entries.values(), key=lambda x: x["start_time"], reverse=True
        )[: self.max_columns - len(panels)]

        # Generate panels for each log
        for log in sorted_logs:
            elapsed = time.time() - log["start_time"]
            panels.append(
                Panel(
                    "\n".join(log["logs"]),
                    title=f"[bold blue]Forward {log['id']}[/] ({elapsed:.1f}s)",
                    width=40,
                )
            )

        return Columns(panels)

    async def __aenter__(self):
        self.live.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.live.stop()
