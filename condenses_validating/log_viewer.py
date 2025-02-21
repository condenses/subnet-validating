from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich.text import Text
from datetime import datetime
import asyncio
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
import aioconsole
from .redis_manager import RedisManager
from .config import CONFIG


class LogViewer:
    def __init__(self):
        self.console = Console()
        self.redis_client = None
        self.redis_manager = None
        self.paused = False
        self.grid_columns = 4
        self.grid_rows = 4
        self.max_cards = self.grid_columns * self.grid_rows
        self._connect_redis()

    def _connect_redis(self):
        """Initialize Redis connection with retry logic"""
        self.redis_client = Redis(
            host=CONFIG.redis.host,
            port=CONFIG.redis.port,
            db=CONFIG.redis.db,
            socket_connect_timeout=2,
            health_check_interval=10,
        )
        self.redis_manager = RedisManager(self.redis_client)

    async def _reconnect_redis(self):
        """Handle Redis reconnection"""
        self.console.print("[yellow]Reconnecting to Redis...[/yellow]")
        await self.redis_client.aclose()
        self._connect_redis()

    def _calculate_grid_size(self):
        """Calculate grid dimensions based on terminal size"""
        terminal_width = self.console.width
        terminal_height = self.console.height
        self.grid_columns = max(1, terminal_width // 30)
        self.grid_rows = max(1, (terminal_height - 4) // 8)  # Reserve space for headers
        self.max_cards = self.grid_columns * self.grid_rows

    def _style_log_message(self, message: str) -> Text:
        """Apply styling based on log level"""
        text = Text()
        level_color_map = {
            "ERROR": "red",
            "WARN": "yellow",
            "WARNING": "yellow",
            "INFO": "green",
            "DEBUG": "dim",
        }

        # Split message into level and content
        for level, color in level_color_map.items():
            if message.startswith(level):
                text.append(f"{level}: ", style=f"bold {color}")
                text.append(message[len(level) + 1 :])
                return text

        # Default styling
        text.append(message, style="dim")
        return text

    def make_log_card(self, uuid: str, logs: list[tuple[str, str]]) -> Panel:
        """Create a panel with styled log messages"""
        if not logs:
            return Panel(
                "[dim]No logs[/dim]",
                title=f"[blue]{uuid[:8]}[/blue]",
                border_style="dim",
            )

        log_text = Text()
        for timestamp, message in logs:
            dt = datetime.fromisoformat(timestamp)
            log_text.append(f"{dt.strftime('%H:%M:%S')} ", style="cyan")
            log_text.append_text(self._style_log_message(message))
            log_text.append("\n")

        return Panel(
            log_text,
            title=f"[blue]{uuid[:8]}[/blue]",
            title_align="left",
            border_style="blue",
            height=8,  # Fixed height for consistent grid
        )

    def make_grid(self, uuids_with_logs: list[tuple[str, list]]) -> Table:
        """Create a responsive grid layout"""
        self._calculate_grid_size()
        grid = Table.grid(expand=True, padding=1)

        for _ in range(self.grid_columns):
            grid.add_column(ratio=1)

        # Create card matrix
        cards = [self.make_log_card(uuid, logs) for uuid, logs in uuids_with_logs]
        cards += [Panel("", border_style="dim")] * (self.max_cards - len(cards))

        # Split into rows
        rows = [
            cards[i : i + self.grid_columns]
            for i in range(0, len(cards), self.grid_columns)
        ]

        # Add rows to grid
        for row in rows[: self.grid_rows]:
            grid.add_row(*row)

        return grid

    async def fetch_recent_uuids(self) -> list:
        """Get UUIDs sorted by recent activity with Redis pipelines"""
        try:
            # Get all log keys
            log_keys = []
            async for key in self.redis_client.scan_iter("log:*"):
                log_keys.append(key.decode())

            # Extract UUIDs and fetch last log timestamps
            uuids = list({key.split(":")[1] for key in log_keys})
            if not uuids:
                return []

            # Pipeline for last log entries
            async with self.redis_client.pipeline() as pipe:
                for uuid in uuids:
                    pipe.lindex(f"log:{uuid}", -1)
                last_logs = await pipe.execute()

            # Parse timestamps and sort
            uuid_timestamps = []
            for uuid, entry in zip(uuids, last_logs):
                if entry:
                    try:
                        timestamp = entry.decode().split("|", 1)[0]
                        dt = datetime.fromisoformat(timestamp)
                        uuid_timestamps.append((uuid, dt.timestamp()))
                    except (ValueError, IndexError):
                        continue

            return sorted(uuid_timestamps, key=lambda x: -x[1])[: self.max_cards]

        except RedisConnectionError:
            await self._reconnect_redis()
            return []

    async def fetch_logs(self, uuids: list) -> list:
        """Fetch logs for UUIDs using pipeline"""
        try:
            async with self.redis_client.pipeline() as pipe:
                for uuid, _ in uuids:
                    pipe.lrange(f"log:{uuid}", -6, -1)
                results = await pipe.execute()

            parsed_logs = []
            for (uuid, _), logs in zip(uuids, results):
                uuid_logs = []
                for log in logs:
                    parts = log.decode().split("|", 1)
                    if len(parts) == 2:
                        uuid_logs.append((parts[0], parts[1]))
                parsed_logs.append((uuid, uuid_logs[-6:]))  # Ensure max 6 logs

            return parsed_logs
        except RedisConnectionError:
            await self._reconnect_redis()
            return []

    async def update_display(self, live: Live) -> None:
        """Update display with latest logs"""
        try:
            recent_uuids = await self.fetch_recent_uuids()
            uuids_with_logs = await self.fetch_logs(recent_uuids)
            grid = self.make_grid(uuids_with_logs)
            live.update(grid)
        except Exception as e:
            live.update(Panel(f"[red]Error: {str(e)}[/]", title="Error"))

    async def handle_input(self):
        """Handle keyboard input"""
        while True:
            try:
                key = await aioconsole.ainput()
                if key.lower() == "q":
                    raise KeyboardInterrupt
                elif key.lower() == "p":
                    self.paused = not self.paused
            except (EOFError, KeyboardInterrupt):
                break

    async def run(self) -> None:
        """Main execution loop"""
        with Live(
            Panel("Connecting...", title="Log Viewer"),
            refresh_per_second=4,
            screen=True,
        ) as live:
            input_task = asyncio.create_task(self.handle_input())
            try:
                while True:
                    if not self.paused:
                        await self.update_display(live)
                    await asyncio.sleep(CONFIG.viewer.refresh_interval)
            except KeyboardInterrupt:
                pass
            finally:
                input_task.cancel()
                await self.redis_client.close()


def start_viewer():
    """Entry point for the log viewer"""
    viewer = LogViewer()
    asyncio.run(viewer.run())


if __name__ == "__main__":
    start_viewer()
