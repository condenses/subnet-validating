from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich.text import Text
from datetime import datetime
import asyncio
from redis.asyncio import Redis
from .redis_manager import RedisManager
from .config import CONFIG

class LogViewer:
    def __init__(self):
        self.console = Console()
        self.redis_client = Redis(
            host=CONFIG.redis.host, 
            port=CONFIG.redis.port, 
            db=CONFIG.redis.db
        )
        self.redis_manager = RedisManager(self.redis_client)
        self.grid_size = 4
        self.max_cards = self.grid_size * self.grid_size

    def make_log_card(self, uuid: str, logs: list[tuple[str, str]]) -> Panel:
        """Create a panel containing log messages for a UUID"""
        if not logs:
            return Panel(
                "[dim]No logs[/dim]",
                title=f"[blue]{uuid[:8]}[/blue]",
                border_style="dim"
            )

        # Format log entries
        log_text = Text()
        for timestamp, message in logs[-6:]:  # Show last 6 logs
            dt = datetime.fromisoformat(timestamp)
            log_text.append(f"{dt.strftime('%H:%M:%S')} ", style="cyan")
            log_text.append(f"{message}\n")

        return Panel(
            log_text,
            title=f"[blue]{uuid[:8]}[/blue]",
            title_align="left",
            border_style="blue"
        )

    def make_grid(self, uuids_with_logs: list[tuple[str, list]]) -> Table:
        """Create a grid of log cards"""
        grid = Table.grid(expand=True, padding=1)
        
        # Add 4 columns of equal width
        for _ in range(self.grid_size):
            grid.add_column(ratio=1)

        # Create rows of cards
        rows = []
        current_row = []
        
        # Fill with available logs
        for uuid, logs in uuids_with_logs:
            current_row.append(self.make_log_card(uuid, logs))
            if len(current_row) == self.grid_size:
                rows.append(current_row)
                current_row = []

        # Fill remaining slots with empty panels
        while len(current_row) < self.grid_size:
            current_row.append(Panel("", border_style="dim"))
        if current_row:
            rows.append(current_row)

        # Add rows to grid
        for row in rows[:self.grid_size]:
            grid.add_row(*row)

        return grid

    async def update_display(self, live: Live) -> None:
        """Update the display with latest logs"""
        # Get all log keys
        log_keys = []
        async for key in self.redis_client.scan_iter("log:*"):
            log_keys.append(key.decode())

        # Get logs for each UUID
        uuids_with_logs = []
        for key in log_keys[-self.max_cards:]:
            uuid = key.split(":")[1]
            logs = await self.redis_manager.get_logs(uuid)
            uuids_with_logs.append((uuid, logs))

        # Update the live display
        grid = self.make_grid(uuids_with_logs)
        live.update(grid)

    async def run(self) -> None:
        """Run the log viewer"""
        with Live(
            Panel("Loading logs...", title="Log Viewer"), 
            refresh_per_second=2,
            screen=True
        ) as live:
            while True:
                try:
                    await self.update_display(live)
                    await asyncio.sleep(0.5)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    live.update(Panel(f"Error: {e}", border_style="red"))
                    await asyncio.sleep(1)

def start_viewer():
    """Start the log viewer"""
    viewer = LogViewer()
    asyncio.run(viewer.run())

if __name__ == "__main__":
    start_viewer()
