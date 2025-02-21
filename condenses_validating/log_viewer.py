import asyncio
from datetime import datetime
from typing import List, Tuple
from collections import deque

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Grid
import redis.asyncio as aioredis


class LogPanel(Static):
    """A widget to display logs as simple text."""

    def __init__(self, uuid: str, logs: List[Tuple[str, str]], **kwargs) -> None:
        self.uuid = uuid
        self.logs = logs
        super().__init__(**kwargs)

    def render(self) -> str:
        # Simple text output without styling
        output = f"{self.uuid[:8]}\n"
        filtered_logs = [
            (ts, msg) for ts, msg in self.logs if "Forward complete" not in msg
        ]
        for timestamp, message in filtered_logs[-4:]:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except Exception:
                formatted_time = timestamp
            output += f"{formatted_time} {message}\n"
        if not filtered_logs:
            output += "No logs available\n"
        return output


class TextualLogViewer(App):
    BINDINGS = [("q", "quit", "Quit")]
    CSS_PATH = "log_viewer.tcss"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.max_panels = 12
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

    async def refresh_logs(self) -> None:
        """Fetch logs and update the grid container."""
        await self.fetch_logs()
        grid = self.query_one("#logs-grid", Grid)

        # Clear existing content
        for child in grid.children:
            child.remove()

        # Left column: set_weights logs
        left_column = Grid(id="left-column")
        for uuid, logs in self.set_weights_logs:
            left_column.mount(LogPanel(uuid, logs, classes="log-text"))

        # Right column: regular logs
        right_column = Grid(id="right-column")
        for uuid, logs in self.regular_logs:
            right_column.mount(LogPanel(uuid, logs, classes="log-text"))

        grid.mount(left_column)
        grid.mount(right_column)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Grid(id="logs-grid")
        yield Footer()

    async def on_mount(self) -> None:
        grid = self.query_one("#logs-grid", Grid)
        grid.styles.grid_template_columns = "1fr 1fr"  # Two equal columns
        self.set_interval(2, self.refresh_logs)

    async def on_unmount(self) -> None:
        await self.redis.close()


if __name__ == "__main__":
    TextualLogViewer().run()
