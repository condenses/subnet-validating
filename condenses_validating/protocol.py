import bittensor as bt
import uuid
from pydantic import Field
from .config import CONFIG


class TextCompressProtocol(bt.Synapse):
    id: str = Field(default_factory=lambda: str(uuid.uuid1()))
    context: str = ""
    compressed_context: str = ""
    user_message: str = ""
    compress_rate: float = 0.0

    @property
    def forward_synapse(self) -> "TextCompressProtocol":
        return TextCompressProtocol(
            context=self.user_message,
        )

    def verify(self) -> tuple[bool, str]:
        if not self.compressed_context:
            return False, "Compressed context is empty"
        if self.compress_rate > CONFIG.validating.max_compress_rate:
            return False, f"Compress rate is too high: {self.compress_rate}"
        return True, "Valid"
