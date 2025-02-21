import asyncio
from datetime import datetime
from typing import List, Tuple

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Grid
import redis.asyncio as aioredis


class LogPanel(Static):
    """A widget to display logs for a specific UUID."""

    def __init__(self, uuid: str, logs: List[Tuple[str, str]], **kwargs) -> None:
        self.uuid = uuid
        self.logs = logs
        super().__init__(**kwargs)

    def render(self) -> str:
        header = f"[bold]{self.uuid[:8]}[/bold]\n"
        body = ""
        # Show the last 6 log entries
        for timestamp, message in self.logs[-6:]:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except Exception:
                formatted_time = timestamp
            # Escape the message to prevent markup interpretation
            escaped_message = message.replace("[", "\\[").replace("]", "\\]")
            body += f"[secondary]{formatted_time}[/secondary] {escaped_message}\n"
        if not body:
            body = "[dim italic]No logs available[/dim italic]"
        return header + body


class TextualLogViewer(App):
    BINDINGS = [("q", "quit", "Quit")]
    CSS_PATH = "log_viewer.tcss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.max_panels = 12  # Reduced to account for the dedicated column
        self.set_weights_logs = []  # Store set_weights logs separately

    async def fetch_logs(self) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """Retrieve log data from Redis."""
        uuids_with_logs = []
        keys = []
        self.set_weights_logs = []  # Reset set_weights logs

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
                keys.append((key, uuid, logs))

        # Only use the most recent non-set_weights keys up to our grid limit
        recent_keys = sorted(keys, key=lambda x: x[0])[-self.max_panels :]
        uuids_with_logs = [(uuid, logs) for _, uuid, logs in recent_keys]

        return uuids_with_logs

    async def refresh_logs(self) -> None:
        """Fetch logs and update the grid container."""
        logs_data = await self.fetch_logs()
        grid = self.query_one("#logs-grid", Grid)

        # Remove all existing panels
        for child in grid.children:
            child.remove()

        # Mount set_weights panels in the first column
        for uuid, logs in self.set_weights_logs[-3:]:  # Show last 3 set_weights logs
            grid.mount(LogPanel(uuid, logs))

        # Mount other panels in remaining columns
        for uuid, logs in logs_data:
            grid.mount(LogPanel(uuid, logs))

    def compose(self) -> ComposeResult:
        # Build the layout: header, grid container, footer.
        yield Header()
        yield Grid(id="logs-grid")
        yield Footer()

    async def on_mount(self) -> None:
        # Configure the grid with 5 columns - first for set_weights, rest for other logs
        grid = self.query_one("#logs-grid", Grid)
        grid.styles.grid_template_columns = "1fr repeat(3, 1fr)"
        # Refresh the logs every 2 seconds.
        self.set_interval(2, self.refresh_logs)

    async def on_unmount(self) -> None:
        # Properly close the Redis connection.
        await self.redis.close()


if __name__ == "__main__":
    TextualLogViewer().run()
