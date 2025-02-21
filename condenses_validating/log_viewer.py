import asyncio
from datetime import datetime
from typing import List, Tuple

from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Header, Footer, Static
import redis.asyncio as aioredis


class LogPanel(Static):
    """Widget to display logs for a specific UUID."""

    def __init__(self, uuid: str, logs: List[Tuple[str, str]], **kwargs) -> None:
        self.uuid = uuid
        self.logs = logs
        super().__init__(**kwargs)

    def render(self) -> str:
        header = f"[bold blue]{self.uuid[:8]}[/bold blue]\n"
        body = ""
        # Show the last 6 log entries
        for timestamp, message in self.logs[-6:]:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except Exception:
                formatted_time = timestamp
            body += f"[cyan]{formatted_time}[/cyan] {message}\n"
        if not body:
            body = "[dim]No logs available[/dim]"
        return header + body


class TextualLogViewer(App):
    """A Textual-based log viewer that displays logs stored in Redis."""

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Connect to Redis (adjust host/port/db as needed)
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.grid = Grid()
        # Maximum number of log panels to show
        self.max_panels = 16

    async def fetch_logs(self) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """
        Fetch logs from Redis.
        Returns a list of tuples (uuid, logs) where logs is a list of (timestamp, message).
        """
        uuids_with_logs = []
        keys = []
        # Scan for keys that start with "log:"
        async for key in self.redis.scan_iter("log:*"):
            keys.append(key)
        # Optionally, only use the most recent keys
        recent_keys = keys[-self.max_panels :]
        for key in recent_keys:
            parts = key.split(":")
            if len(parts) < 2:
                continue
            uuid = parts[1]
            logs_dict = await self.redis.hgetall(key)
            # Sort log entries by timestamp
            logs = sorted(logs_dict.items(), key=lambda x: x[0])
            uuids_with_logs.append((uuid, logs))
        return uuids_with_logs

    async def refresh_logs(self) -> None:
        """Fetch the latest logs from Redis and update the grid."""
        uuids_with_logs = await self.fetch_logs()
        # Clear any existing children in the grid
        self.grid.clear()
        # Create and add a LogPanel for each set of logs
        for uuid, logs in uuids_with_logs:
            panel = LogPanel(uuid, logs)
            self.grid.mount(panel)
        await self.grid.refresh()

    async def on_mount(self) -> None:
        """Set up the layout and start the periodic refresh."""
        await self.screen.dock(Header(), edge="top")
        await self.screen.dock(Footer(), edge="bottom")
        # Configure grid: 4 columns (adjust grid as needed)
        self.grid.styles.grid_template_columns = "repeat(4, 1fr)"
        await self.screen.dock(self.grid, edge="left", size=100)
        # Refresh logs every 2 seconds
        self.set_interval(2, self.refresh_logs)

    async def on_unmount(self) -> None:
        """Clean up the Redis connection when the app closes."""
        await self.redis.close()


if __name__ == "__main__":
    TextualLogViewer().run()
