import asyncio
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from redis.asyncio import Redis
from .redis_manager import RedisManager
from .config import CONFIG


class LogViewer:
    def __init__(self, grid_size: int = 4):
        self.console = Console()
        # Enable automatic decoding to simplify key handling
        self.redis_client = Redis(
            host=CONFIG.redis.host,
            port=CONFIG.redis.port,
            db=CONFIG.redis.db,
            decode_responses=True,
        )
        self.redis_manager = RedisManager(self.redis_client)
        self.grid_size = grid_size
        self.max_cards = grid_size * grid_size

    def make_log_card(self, uuid: str, logs: list[tuple[str, str]]) -> Panel:
        """Create a panel containing log messages for a UUID."""
        title = f"[blue]{uuid[:8]}[/blue]"
        if not logs:
            return Panel("[dim]No logs[/dim]", title=title, border_style="dim")

        log_text = Text()
        # Show the last 6 logs
        for timestamp, message in logs[-6:]:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except Exception:
                formatted_time = timestamp  # fallback if parsing fails
            log_text.append(f"{formatted_time} ", style="cyan")
            log_text.append(f"{message}\n")
        return Panel(log_text, title=title, title_align="left", border_style="blue")

    def make_grid(self, uuids_with_logs: list[tuple[str, list]]) -> Table:
        """Create a grid of log cards."""
        grid = Table.grid(expand=True, padding=1)
        for _ in range(self.grid_size):
            grid.add_column(ratio=1)

        rows = []
        current_row = []
        for uuid, logs in uuids_with_logs:
            current_row.append(self.make_log_card(uuid, logs))
            if len(current_row) == self.grid_size:
                rows.append(current_row)
                current_row = []
        # Fill remaining slots with empty panels
        if current_row:
            while len(current_row) < self.grid_size:
                current_row.append(Panel("", border_style="dim"))
            rows.append(current_row)

        # Only include a maximum number of rows to fill the grid
        for row in rows[: self.grid_size]:
            grid.add_row(*row)
        return grid

    async def update_display(self, live: Live) -> None:
        """Fetch the latest logs and update the live display."""
        # Get all log keys using scan_iter (keys are already decoded)
        log_keys = [key for key in self.redis_client.scan_iter("log:*")]
        # Select the most recent keys based on our grid limit
        recent_keys = log_keys[-self.max_cards :]
        uuids = []
        tasks = []
        for key in recent_keys:
            parts = key.split(":")
            if len(parts) >= 2:
                uuid = parts[1]
                uuids.append(uuid)
                tasks.append(self.redis_manager.get_logs(uuid))
        # Fetch logs concurrently
        logs_results = await asyncio.gather(*tasks, return_exceptions=False)
        uuids_with_logs = list(zip(uuids, logs_results))

        grid = self.make_grid(uuids_with_logs)
        # Wrap the grid in a parent panel that shows the last update time
        updated_panel = Panel(
            grid,
            title="Log Viewer",
            subtitle=f"Updated: {datetime.now().strftime('%H:%M:%S')}",
            border_style="blue",
        )
        live.update(updated_panel)

    async def run(self) -> None:
        """Run the live log viewer."""
        try:
            with Live(
                Panel("Loading logs...", title="Log Viewer", border_style="blue"),
                refresh_per_second=2,
                screen=True,
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
        finally:
            await self.redis_client.close()


def start_viewer():
    """Start the log viewer."""
    viewer = LogViewer()
    asyncio.run(viewer.run())


if __name__ == "__main__":
    start_viewer()
