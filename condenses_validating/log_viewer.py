from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.style import Style
from datetime import datetime
from typing import List, Dict, Any


class LogViewer:
    def __init__(self):
        self.console = Console()

    def create_log_card(self, log_entry: Dict[str, Any]) -> Panel:
        """Create a pretty panel for a single log entry."""
        # Create a table for log details
        table = Table(show_header=False, show_edge=False, box=None)
        table.add_column("Key", style="bold cyan")
        table.add_column("Value")

        # Format timestamp if present
        timestamp = log_entry.get("timestamp")
        if timestamp:
            if isinstance(timestamp, (int, float)):
                timestamp = datetime.fromtimestamp(timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            table.add_row("Time", timestamp)

        # Add other log fields
        for key, value in log_entry.items():
            if key != "timestamp":
                # Format value based on type
                if isinstance(value, (dict, list)):
                    formatted_value = Text(str(value), style="yellow")
                elif isinstance(value, bool):
                    formatted_value = Text(
                        str(value), style="green" if value else "red"
                    )
                elif isinstance(value, (int, float)):
                    formatted_value = Text(str(value), style="blue")
                else:
                    formatted_value = Text(str(value))

                table.add_row(key.capitalize(), formatted_value)

        # Create panel with border style based on log level
        level = log_entry.get("level", "").lower()
        border_style = {
            "error": "red",
            "warning": "yellow",
            "info": "blue",
            "debug": "grey70",
        }.get(level, "white")

        return Panel(
            table,
            title=f"[{level.upper()}]" if level else "",
            border_style=border_style,
            padding=(1, 2),
        )

    def display_logs(self, logs: List[Dict[str, Any]]) -> None:
        """Display multiple log entries as cards."""
        # Clear screen first
        self.console.clear()

        # Create layout
        layout = Layout()
        layout.split_column(Layout(name="header", size=3), Layout(name="main"))

        # Add header
        header = Panel(
            Text("Log Viewer", style="bold white", justify="center"), style="blue"
        )
        layout["header"].update(header)

        # Display each log as a card
        for log in logs:
            self.console.print(self.create_log_card(log))
            # Add small spacing between cards
            self.console.print()


# Example usage
if __name__ == "__main__":
    # Sample logs for demonstration
    sample_logs = [
        {
            "timestamp": datetime.now().timestamp(),
            "level": "info",
            "message": "Application started",
            "details": {"version": "1.0.0", "environment": "production"},
        },
        {
            "timestamp": datetime.now().timestamp(),
            "level": "error",
            "message": "Failed to connect to database",
            "error_code": 500,
            "retry_count": 3,
        },
        {
            "timestamp": datetime.now().timestamp(),
            "level": "warning",
            "message": "High memory usage detected",
            "memory_usage": "85%",
            "threshold": "80%",
        },
    ]

    # Create and use the log viewer
    viewer = LogViewer()
    viewer.display_logs(sample_logs)
