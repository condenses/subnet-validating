import asyncio
from redis.asyncio import Redis
from datetime import datetime, timedelta
import argparse
from typing import Optional, List, Tuple, Dict
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.box import ROUNDED
from rich.columns import Columns
from rich.style import Style
from rich import box
from collections import defaultdict

console = Console()


class LogCard:
    def __init__(self, uuid: str, max_logs: int = 5):
        self.uuid = uuid
        self.max_logs = max_logs
        self.logs: List[Tuple[datetime, str]] = []

    def add_log(self, timestamp: datetime, message: str) -> None:
        self.logs.append((timestamp, message))
        self.logs.sort(key=lambda x: x[0])
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs :]

    def create_panel(self) -> Panel:
        """Create a panel representing this log card."""
        content = Text()

        # Add UUID header
        content.append(f"UUID: {self.uuid}\n", style="bold magenta")
        content.append("─" * 40 + "\n", style="grey50")

        # Add logs
        if not self.logs:
            content.append("No recent logs", style="italic grey70")
        else:
            for timestamp, message in self.logs:
                time_str = timestamp.strftime("%H:%M:%S")
                content.append(time_str, style="cyan")
                content.append(" | ", style="grey50")
                content.append(f"{message}\n", style="bright_white")

        return Panel(
            content,
            box=box.ROUNDED,
            title=f"[bold blue]Log Stream",
            border_style="blue",
            width=50,
            height=10,
            padding=(0, 1),
        )


class LogViewer:
    def __init__(
        self,
        redis_client: Redis,
        follow: bool = False,
        last_minutes: int = 60,
        last_n_logs: int = 5,
        cards_per_row: int = 3,
    ):
        self.redis = redis_client
        self.follow = follow
        self.last_minutes = last_minutes
        self.last_n_logs = last_n_logs
        self.cards_per_row = cards_per_row
        self.layout = self._create_layout()
        self.log_cards: Dict[str, LogCard] = {}

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
        title = f"Redis Log Dashboard - Showing last {self.last_minutes} minutes"
        subtitle = f"Monitoring {len(self.log_cards)} active log streams"

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

    async def _fetch_logs(self) -> None:
        """Fetch and process logs from Redis."""
        cutoff_time = datetime.now() - timedelta(minutes=self.last_minutes)

        # Get all log keys
        async for key in self.redis.scan_iter("log:*"):
            uuid = key.decode().replace("log:", "")

            # Create card if it doesn't exist
            if uuid not in self.log_cards:
                self.log_cards[uuid] = LogCard(uuid, self.last_n_logs)

            # Get logs for this UUID
            logs = await self.redis.hgetall(key.decode())
            if logs:
                for ts_bytes, msg_bytes in logs.items():
                    timestamp = datetime.fromisoformat(ts_bytes.decode())
                    if timestamp >= cutoff_time:
                        message = msg_bytes.decode()
                        self.log_cards[uuid].add_log(timestamp, message)

    def _create_card_grid(self) -> Columns:
        """Create a grid of cards using Columns."""
        # Create panels for each card
        panels = [card.create_panel() for card in self.log_cards.values()]

        # Organize panels into columns
        return Columns(
            panels, equal=True, align="center", number_in_row=self.cards_per_row
        )

    async def update_display(self, live: Live) -> None:
        """Update the display with fresh log data."""
        await self._fetch_logs()

        # Update layout components
        self.layout["header"].update(self._create_header())
        self.layout["main"].update(self._create_card_grid())
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
    parser = argparse.ArgumentParser(description="Redis Log Dashboard")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
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
        default=5,
        help="Number of most recent logs to show per card",
    )
    parser.add_argument(
        "--cards-per-row",
        "-c",
        type=int,
        default=3,
        help="Number of cards to show per row",
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
            follow=args.follow,
            last_minutes=args.minutes,
            last_n_logs=args.last_n,
            cards_per_row=args.cards_per_row,
        )
        await viewer.run()
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
