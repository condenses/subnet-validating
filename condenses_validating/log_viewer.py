import asyncio
from redis.asyncio import Redis
from datetime import datetime, timedelta
import argparse
from typing import Optional, List, Dict, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.box import ROUNDED
from rich.style import Style
from rich.columns import Columns
from rich.padding import Padding
from rich import box

console = Console()


class LogCard:
    def __init__(self, uuid: str, max_logs: int = 5):
        self.uuid = uuid
        self.max_logs = max_logs
        self.logs: List[Tuple[datetime, str]] = []

    def update_logs(self, logs: List[Tuple[datetime, str]]) -> None:
        """Update the logs for this card, keeping only the most recent ones."""
        self.logs = sorted(logs, key=lambda x: x[0])[-self.max_logs :]

    def render(self) -> Panel:
        """Render the card as a Rich Panel."""
        content = Text()

        # Add UUID header
        short_uuid = self.uuid.replace("log:", "")[:8] + "..."
        content.append(f"UUID: {short_uuid}\n", style="bold magenta")
        content.append("─" * 30 + "\n", style="dim")

        # Add logs
        if not self.logs:
            content.append("No recent logs", style="dim italic")
        else:
            for timestamp, message in self.logs:
                time_str = timestamp.strftime("%H:%M:%S")
                content.append(time_str, style="cyan")
                content.append(" | ", style="dim")
                content.append(f"{message}\n", style="bright_white")

        return Panel(
            Padding(content, (0, 1)),
            box=box.ROUNDED,
            title=f"[bold blue]Forward {short_uuid}[/bold blue]",
            border_style="blue",
        )


class CardLogViewer:
    def __init__(
        self,
        redis_client: Redis,
        follow: bool = False,
        last_minutes: int = 60,
        logs_per_card: int = 5,
        columns: int = 3,
    ):
        self.redis = redis_client
        self.follow = follow
        self.last_minutes = last_minutes
        self.logs_per_card = logs_per_card
        self.columns = columns
        self.cards: Dict[str, LogCard] = {}
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
        """Create the header panel."""
        title = "Redis Log Dashboard"
        subtitle = f"Watching all logs from last {self.last_minutes} minutes"

        header_text = Text()
        header_text.append(title + "\n", style="bold white on blue")
        header_text.append(subtitle, style="italic")

        return Panel(header_text, box=ROUNDED, style="blue", padding=(0, 2))

    def _create_footer(self) -> Panel:
        """Create the footer panel."""
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
            key_str = key.decode()

            # Create card if it doesn't exist
            if key_str not in self.cards:
                self.cards[key_str] = LogCard(key_str, self.logs_per_card)

            # Fetch logs for this key
            logs = await self.redis.hgetall(key_str)
            if logs:
                card_logs = []
                for ts_bytes, msg_bytes in logs.items():
                    timestamp = datetime.fromisoformat(ts_bytes.decode())
                    if timestamp >= cutoff_time:
                        message = msg_bytes.decode()
                        card_logs.append((timestamp, message))

                self.cards[key_str].update_logs(card_logs)

    def _render_cards(self) -> Columns:
        """Render all cards in a grid layout."""
        rendered_cards = [card.render() for card in self.cards.values()]

        # If no cards, show a message
        if not rendered_cards:
            return Panel("No active log streams found", style="dim")

        return Columns(
            rendered_cards, equal=True, expand=True
        )

    async def update_display(self, live: Live) -> None:
        """Update the display with fresh log data."""
        await self._fetch_logs()

        # Update layout components
        self.layout["header"].update(self._create_header())
        self.layout["main"].update(self._render_cards())
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
    parser = argparse.ArgumentParser(description="Card-based Redis Log Viewer")
    parser.add_argument("--host", default="localhost", help="Redis host")
    parser.add_argument("--port", type=int, default=6379, help="Redis port")
    parser.add_argument(
        "--follow", "-f", action="store_true", help="Continuously watch for new logs"
    )
    parser.add_argument(
        "--minutes", "-m", type=int, default=60, help="Show logs from last N minutes"
    )
    parser.add_argument(
        "--logs-per-card",
        "-l",
        type=int,
        default=5,
        help="Number of logs to show per card",
    )
    parser.add_argument(
        "--columns",
        "-c",
        type=int,
        default=3,
        help="Number of columns in the card grid",
    )

    args = parser.parse_args()

    redis = Redis(host=args.host, port=args.port, decode_responses=False)

    try:
        viewer = CardLogViewer(
            redis,
            follow=args.follow,
            last_minutes=args.minutes,
            logs_per_card=args.logs_per_card,
            columns=args.columns,
        )
        await viewer.run()
    finally:
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
