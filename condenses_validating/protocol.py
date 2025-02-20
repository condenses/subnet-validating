import bittensor as bt
import tiktoken
from pydantic import Field
from .config import CONFIG


TOKENIZER = tiktoken.get_encoding("gpt-4o")


class TextCompresssProtocol(bt.Synapse):
    context: str = Field(
        description="The context of the message", frozen=True, default=""
    )
    compressed_context: str = Field(
        description="The compressed context of the message", frozen=False, default=""
    )
    user_message: str = Field(description="The user message", frozen=True, default="")

    @property
    def forward_synapse(self) -> "TextCompresssProtocol":
        return TextCompresssProtocol(
            context=self.user_message,
        )

    @property
    def compress_rate(self) -> float:
        original_tokens = TOKENIZER.encode(self.context)
        compressed_tokens = TOKENIZER.encode(self.compressed_context)
        return len(compressed_tokens) / len(original_tokens)

    def verify(self) -> tuple[bool, str]:
        if not self.compressed_context:
            return False, "Compressed context is empty"
        if self.compress_rate > CONFIG.validating.max_compress_rate:
            return False, f"Compress rate is too high: {self.compress_rate}"
        return True, "Valid"
