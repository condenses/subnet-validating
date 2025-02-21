import asyncio
from redis.asyncio import Redis
from datetime import datetime, timedelta
import argparse
from typing import Optional, List, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED
from rich.style import Style

console = Console()


class LogViewer:
    def __init__(
        self,
        redis_client: Redis,
        forward_uuid: Optional[str] = None,
        follow: bool = False,
        last_minutes: int = 60,
        last_n_logs: int = 10,
    ):
        self.redis = redis_client
        self.forward_uuid = forward_uuid
        self.follow = follow
        self.last_minutes = last_minutes
        self.last_n_logs = last_n_logs
        self.layout = self._create_layout()

    def _create_layout(self) -> Layout:
        """Create the main layout for the log viewer."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )
        return layout

    def _create_header(self) -> Panel:
        """Create the header panel with viewing information."""
        title = "Redis Log Viewer"
        if self.forward_uuid:
            subtitle = f"Watching logs for UUID: {self.forward_uuid}"
        else:
            subtitle = f"Watching all logs from last {self.last_minutes} minutes"

        header_text = Text()
        header_text.append(title + "\n", style="bold white on blue")
        header_text.append(subtitle, style="italic")

        return Panel(header_text, box=ROUNDED, style="blue", padding=(0, 2))

    def _create_footer(self) -> Panel:
        """Create the footer panel with controls information."""
        footer_text = Text()
        footer_text.append("Press ", style="grey70")
        footer_text.append("Ctrl+C", style="bold red")
        footer_text.append(" to exit", style="grey70")
        if self.follow:
            footer_text.append(" | Following new logs", style="green")

        return Panel(footer_text, box=ROUNDED, style="blue")

    def _create_log_table(self, logs: List[Tuple[datetime, str, str]]) -> Table:
        """Create a table containing the log entries."""
        table = Table(box=ROUNDED, expand=True, row_styles=["dim", ""])

        table.add_column("Timestamp", style="cyan", no_wrap=True)
        table.add_column("UUID", style="magenta")
        table.add_column("Message", style="green")

        for timestamp, uuid, message in logs:
            # Extract UUID from the key string
            uuid_clean = uuid.replace("log:", "")
            table.add_row(
                timestamp.isoformat(),
                uuid_clean,
                Text(message, style="bright_white", overflow="fold"),
            )

        return table

    async def _fetch_logs(self) -> List[Tuple[datetime, str, str]]:
        """Fetch and process logs from Redis."""
        all_logs = []
        cutoff_time = datetime.now() - timedelta(minutes=self.last_minutes)

        if self.forward_uuid:
            # Get logs for specific forward UUID
            key = f"log:{self.forward_uuid}"
            logs = await self.redis.hgetall(key)
            if logs:
                for ts_bytes, msg_bytes in logs.items():
                    timestamp = datetime.fromisoformat(ts_bytes.decode())
                    if timestamp >= cutoff_time:
                        message = msg_bytes.decode()
                        all_logs.append((timestamp, key, message))
        else:
            # Get all recent log keys
            async for key in self.redis.scan_iter("log:*"):
                key_str = key.decode()
                logs = await self.redis.hgetall(key_str)
                if logs:
                    for ts_bytes, msg_bytes in logs.items():
                        timestamp = datetime.fromisoformat(ts_bytes.decode())
                        if timestamp >= cutoff_time:
                            message = msg_bytes.decode()
                            all_logs.append((timestamp, key_str, message))

        # Sort logs by timestamp and get the most recent ones
        return sorted(all_logs, key=lambda x: x[0])[-self.last_n_logs :]

    async def update_display(self, live: Live) -> None:
        """Update the display with fresh log data."""
        logs = await self._fetch_logs()

        # Update layout components
        self.layout["header"].update(self._create_header())
        self.layout["main"].update(self._create_log_table(logs))
        self.layout["footer"].update(self._create_footer())

        live.update(self.layout)

    async def run(self) -> None:
        """Run the log viewer."""
        with Live(
            self.layout, console=console, screen=True, refresh_per_second=4
        ) as live:
            try:
                while True:
                    await self.update_display(live)
                    if not self.follow:
                        break
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass


async def main():
    parser = argparse.ArgumentParser(description="Enhanced Redis Log Viewer")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument("--forward-uuid", help="Specific forward UUID to watch")
    parser.add_argument(
        "--follow", "-f", action="store_true", help="Continuously watch for new logs"
    )
    parser.add_argument(
        "--minutes", "-m", type=int, default=60, help="Show logs from last N minutes"
    )
    parser.add_argument(
        "--last-n",
        "-n",
        type=int,
        default=10,
        help="Number of most recent logs to show",
    )

    args = parser.parse_args()

    redis = Redis(
        host=args.host,
        port=args.port,
        decode_responses=False,  # Keep as bytes for consistent handling
    )

    try:
        viewer = LogViewer(
            redis,
            forward_uuid=args.forward_uuid,
            follow=args.follow,
            last_minutes=args.minutes,
            last_n_logs=args.last_n,
        )
        await viewer.run()
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
