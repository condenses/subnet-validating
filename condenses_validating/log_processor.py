from rich.console import Console
from rich.columns import Columns
from rich.panel import Panel
from rich.live import Live
from collections import deque
import time
import asyncio


class ForwardLog:
    def __init__(self, max_columns=4):
        self.console = Console()
        self.columns_data = deque(maxlen=max_columns)
        self.live = Live(console=self.console, refresh_per_second=4)

    def add_log(self, synapse_id: str, message: str):
        # Find existing column for this synapse_id or create new
        column_found = False
        for column in self.columns_data:
            if column["id"] == synapse_id:
                column["logs"].append(message)
                column_found = True
                break

        if not column_found:
            self.columns_data.append(
                {"id": synapse_id, "logs": [message], "start_time": time.time()}
            )
        self.live.update(self.render())

    async def remove_log(self, forward_uuid: str, duration: float = 5):
        await asyncio.sleep(duration)
        for i, column in enumerate(self.columns_data):
            if column["id"] == forward_uuid:
                self.columns_data.remove(column)
                break

    def render(self):
        panels = []
        for column in self.columns_data:
            elapsed = time.time() - column["start_time"]
            content = "\n".join(column["logs"])
            panels.append(
                Panel(
                    content,
                    title=f"[bold blue]Forward {column['id']}[/] ({elapsed:.1f}s)",
                    width=40,
                )
            )
        return Columns(panels)

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.live.stop()
