import bittensor as bt
import tiktoken
from pydantic import Field
from .config import CONFIG


TOKENIZER = tiktoken.encoding_for_model("gpt-4o")


class TextCompressProtocol(bt.Synapse):
    context: str = ""
    compressed_context: str = ""
    user_message: str = ""

    @property
    def forward_synapse(self) -> "TextCompressProtocol":
        return TextCompressProtocol(
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
