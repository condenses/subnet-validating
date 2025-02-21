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
        self.paused = False
        self.command_mode = False
        self.current_command = ""
        self.command_result = None

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
        # Create main grid for logs
        grid = Table.grid(expand=True, padding=1)
        for _ in range(self.grid_size):
            grid.add_column(ratio=1)

        # Add command result panel if there's a result
        if hasattr(self, "command_result"):
            result_panel = Panel(
                self.command_result, title="Command Result", border_style="yellow"
            )
            grid.add_row(result_panel)
            delattr(self, "command_result")  # Clear the result after displaying

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

        # Add footer with commands
        footer = Table.grid(padding=1)
        footer.add_column(ratio=1)

        # Create command bar
        command_text = Text()
        if self.command_mode:
            command_text.append("Command: ", style="bold yellow")
            command_text.append(self.current_command, style="yellow")
        else:
            status = "[red]PAUSED[/red]" if self.paused else "[green]RUNNING[/green]"
            command_text.append(f"Status: {status} | ", style="bold")
            command_text.append("Commands: ", style="bold")
            command_text.append("[yellow]p[/yellow]:pause ", style="dim")
            command_text.append("[yellow]r[/yellow]:resume ", style="dim")
            command_text.append("[yellow]q[/yellow]:quit ", style="dim")
            command_text.append("[yellow]/:command[/yellow]", style="dim")

        footer.add_row(Panel(command_text, border_style="blue"))

        # Combine log grid and footer
        final_grid = Table.grid(expand=True)
        final_grid.add_column()
        final_grid.add_row(grid)
        final_grid.add_row(footer)
        return final_grid

    async def update_display(self, live: Live) -> None:
        """Fetch the latest logs and update the live display."""
        log_keys = []
        # Use async for to iterate over the async generator
        async for key in self.redis_client.scan_iter("log:*"):
            # No need to decode since decode_responses=True
            log_keys.append(key)

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

    async def handle_input(self) -> None:
        """Handle keyboard input for commands."""
        while True:
            if self.console.is_terminal:
                import sys
                import termios
                import tty

                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    ch = sys.stdin.read(1)

                    if self.command_mode:
                        if ch == "\r":  # Enter key
                            await self.execute_command(self.current_command)
                            self.command_mode = False
                            self.current_command = ""
                        elif ch == "\x7f":  # Backspace
                            self.current_command = self.current_command[:-1]
                        else:
                            self.current_command += ch
                    else:
                        if ch == "p":
                            self.paused = True
                        elif ch == "r":
                            self.paused = False
                        elif ch == "q":
                            raise KeyboardInterrupt
                        elif ch == "/":
                            self.command_mode = True

                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            await asyncio.sleep(0.1)

    async def execute_command(self, command: str) -> None:
        """Execute the entered command."""
        parts = command.strip().lower().split()
        if not parts:
            return

        cmd = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        if cmd == "clear":
            # Add command handling logic here
            pass
        elif cmd == "latest":
            # Show latest N logs (default 5)
            n = int(args[0]) if args else 5
            logs = await self.redis_manager.get_latest_logs(n)
            self.command_result = self.format_latest_logs(logs)
        elif cmd == "find":
            # Search for logs containing a string
            if not args:
                self.command_result = "Usage: find <search_term>"
                return
            search_term = " ".join(args)
            logs = await self.redis_manager.search_logs(search_term)
            self.command_result = self.format_latest_logs(logs)

    def format_latest_logs(self, logs: list[tuple[str, str, str]]) -> Text:
        """Format logs for display in command result."""
        result = Text()
        for uuid, timestamp, message in logs:
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M:%S")
            except Exception:
                formatted_time = timestamp
            result.append(f"{uuid[:8]} ", style="blue")
            result.append(f"{formatted_time} ", style="cyan")
            result.append(f"{message}\n")
        return result if result else Text("No matching logs found")

    async def run(self) -> None:
        """Run the live log viewer."""
        try:
            with Live(
                Panel("Loading logs...", title="Log Viewer", border_style="blue"),
                refresh_per_second=2,
                screen=True,
            ) as live:
                # Start input handling in a separate task
                input_task = asyncio.create_task(self.handle_input())

                while True:
                    try:
                        if not self.paused:
                            await self.update_display(live)
                        await asyncio.sleep(0.5)
                    except KeyboardInterrupt:
                        break
                    except Exception as e:
                        live.update(Panel(f"Error: {e}", border_style="red"))
                        await asyncio.sleep(1)

                # Cancel input handling task
                input_task.cancel()
                try:
                    await input_task
                except asyncio.CancelledError:
                    pass

        finally:
            await self.redis_client.close()


def start_viewer():
    """Start the log viewer."""
    viewer = LogViewer()
    asyncio.run(viewer.run())


if __name__ == "__main__":
    start_viewer()
