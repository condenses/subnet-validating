import asyncio
import json
from collections import deque
from datetime import datetime

import redis.asyncio as aioredis
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static, Header, Footer


class LogViewerApp(App):
    """A Textual app to display logs from Redis."""

    CSS = """
    Screen {
        layout: vertical;
    }
    .log-container {
        border: solid green;
        height: 1fr;
    }
    .log-title {
        background: green;
        color: black;
    }
    .log-content {
        padding: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.redis = aioredis.Redis(
            host="localhost", port=6379, db=0, decode_responses=True
        )
        self.set_weights_logs = deque(maxlen=6)
        self.regular_logs = deque(maxlen=6)
        self.forward_completed_logs = deque(maxlen=6)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with VerticalScroll(id="set-weights-container", classes="log-container"):
                yield Static("Set Weights Logs", classes="log-title")
                self.set_weights_log_widget = Static(classes="log-content")
                yield self.set_weights_log_widget
            with VerticalScroll(id="batch-logs-container", classes="log-container"):
                yield Static("Batch Logs", classes="log-title")
                self.batch_logs_widget = Static(classes="log-content")
                yield self.batch_logs_widget
            with VerticalScroll(
                id="forward-completed-container", classes="log-container"
            ):
                yield Static("Forward Completed Logs", classes="log-title")
                self.forward_completed_log_widget = Static(classes="log-content")
                yield self.forward_completed_log_widget
        yield Footer()

    async def fetch_logs(self):
        """Retrieve log data from Redis."""
        self.set_weights_logs.clear()
        self.regular_logs.clear()
        self.forward_completed_logs.clear()

        async for key in self.redis.scan_iter("log:*"):
            parts = key.split(":")
            if len(parts) < 2:
                continue
            uuid = parts[1]
            logs_dict = await self.redis.hgetall(key)
            logs = sorted(logs_dict.items(), key=lambda x: x[0])

            if "set_weights" in uuid:
                self.set_weights_logs.append((uuid, logs))
            else:
                for timestamp, message in logs:
                    if "Forward complete" in message:
                        self.forward_completed_logs.append((uuid, logs))
                        break
                else:
                    self.regular_logs.append((uuid, logs))

        # Sort regular_logs by the latest timestamp in each log entry
        self.regular_logs = deque(
            sorted(self.regular_logs, key=lambda x: x[1][-1][0], reverse=True), maxlen=6
        )

    def format_logs(self, logs):
        """Format logs for display."""
        formatted_logs = []
        for uuid, log_entries in logs:
            formatted_logs.append(f"--- {uuid[:16]} ---")
            for timestamp, message in log_entries:
                try:
                    dt = datetime.fromisoformat(timestamp)
                    formatted_time = dt.strftime("%H:%M:%S")
                except ValueError:
                    formatted_time = timestamp

                escaped_message = message.replace("[", "\\[").replace("]", "\\]")

                formatted_logs.append(f"{formatted_time} {escaped_message}")
        return "\n".join(formatted_logs)

    async def update_logs(self):
        """Fetch and display logs."""
        while True:
            await self.fetch_logs()
            self.set_weights_log_widget.update(self.format_logs(self.set_weights_logs))
            self.batch_logs_widget.update(self.format_logs(self.regular_logs))
            self.forward_completed_log_widget.update(
                self.format_logs(self.forward_completed_logs)
            )
            await asyncio.sleep(2)

    async def on_mount(self):
        """Start the log fetching loop when the app mounts."""
        self.run_worker(self.update_logs())

    async def on_unmount(self):
        """Close the Redis connection when the app unmounts."""
        await self.redis.close()


if __name__ == "__main__":
    LogViewerApp().run()
