import bittensor as bt
import random
from pydantic import Field
from .config import CONFIG


def random_uuid(k=4):
    return "".join(random.choices("0123456789abcdef", k=k))


class TextCompressProtocol(bt.Synapse):
    id: str = Field(default_factory=lambda: random_uuid())
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
