from datetime import datetime
from functools import partial
from typing import List, Tuple

from textual import on, work
from textual.app import App, ComposeResult
from textual.command import Hit, Provider
from textual.containers import Grid
from textual.message import Message
from textual.widgets import Header, Footer, Static
import redis.asyncio as aioredis


class LogPanel(Static):
    """Widget to display logs for a specific UUID."""

    DEFAULT_CSS = """
    LogPanel {
        border: solid $primary;
        padding: 1;
        height: auto;
    }
    
    LogPanel > .uuid {
        color: $accent;
        text-style: bold;
    }
    
    LogPanel > .timestamp {
        color: $warning;
    }
    
    LogPanel > .empty {
        color: $text-disabled;
        text-style: italic;
    }
    """

    class PanelSelected(Message):
        """Message sent when panel is selected."""

        def __init__(self, uuid: str) -> None:
            self.uuid = uuid
            super().__init__()

    def __init__(self, uuid: str, logs: List[Tuple[str, str]], **kwargs) -> None:
        self.uuid = uuid
        self.logs = logs
        super().__init__(**kwargs)

    def render(self) -> str:
        """Render the log panel content."""
        header = f"[@click=select_panel]{self.uuid[:8]}[/]"
        body = ""
        # Show the last 6 log entries
        for timestamp, message in self.logs[-6:]:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except ValueError:
                formatted_time = timestamp
            body += f"\n[timestamp]{formatted_time}[/] {message}"

        if not body:
            return f"{header}\n[empty]No logs available[/]"
        return header + body

    @on(Static.Click)
    def select_panel(self) -> None:
        """Handle panel selection."""
        self.post_message(self.PanelSelected(self.uuid))


class LogCommands(Provider):
    """Command palette provider for log actions."""

    async def search(self, query: str) -> Hit:
        """Search available commands."""
        matcher = self.matcher(query)

        commands = [
            ("refresh", "Refresh logs now"),
            ("clear", "Clear all logs"),
            ("export", "Export logs to file"),
        ]

        for command, description in commands:
            score = matcher.match(command)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(command),
                    partial(self.app.action_command, command),
                    description,
                )


class TextualLogViewer(App):
    """A Textual-based log viewer that displays logs stored in Redis."""

    CSS = """
    Grid {
        grid-size: 4;
        grid-gutter: 1;
        padding: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("c", "clear", "Clear"),
        ("ctrl+\\", "command_palette", "Commands"),
    ]

    COMMANDS = App.COMMANDS | {LogCommands}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.max_panels = 16

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Grid()
        yield Footer()

    @work
    async def fetch_logs(self) -> List[Tuple[str, List[Tuple[str, str]]]]:
        """Fetch logs from Redis."""
        try:
            uuids_with_logs = []
            keys = []
            async for key in self.redis.scan_iter("log:*"):
                keys.append(key)

            recent_keys = keys[-self.max_panels :]
            for key in recent_keys:
                uuid = key.split(":", 1)[1]
                logs_dict = await self.redis.hgetall(key)
                logs = sorted(logs_dict.items(), key=lambda x: x[0])
                uuids_with_logs.append((uuid, logs))
            return uuids_with_logs
        except aioredis.RedisError as e:
            self.notify(f"Redis error: {e}", severity="error")
            return []

    async def action_refresh(self) -> None:
        """Refresh the log display."""
        uuids_with_logs = await self.fetch_logs()
        grid = self.query_one(Grid)
        grid.remove_children()
        for uuid, logs in uuids_with_logs:
            grid.mount(LogPanel(uuid, logs))

    async def action_clear(self) -> None:
        """Clear all logs from Redis."""
        try:
            async for key in self.redis.scan_iter("log:*"):
                await self.redis.delete(key)
            await self.action_refresh()
            self.notify("Logs cleared")
        except aioredis.RedisError as e:
            self.notify(f"Failed to clear logs: {e}", severity="error")

    async def action_command(self, command: str) -> None:
        """Handle command palette actions."""
        if command == "refresh":
            await self.action_refresh()
        elif command == "clear":
            await self.action_clear()
        elif command == "export":
            self.notify("Export not implemented yet")

    def on_mount(self) -> None:
        """Set up the app when mounted."""
        self.set_interval(2, self.action_refresh)

    async def on_unmount(self) -> None:
        """Clean up when app closes."""
        await self.redis.close()


if __name__ == "__main__":
    app = TextualLogViewer()
    app.run()
