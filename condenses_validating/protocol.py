import bittensor as bt
import tiktoken
from text_compress_scoring.schemas import Message
from .config import CONFIG

TOKENIZER = tiktoken.get_encoding("gpt-4o")


class TextCompresssProtocol(bt.Synapse):
    context: str = ""
    compressed_context: str = ""
    user_message: Message = Message(role="user", content="", is_compressed=False)
    assistant_message: Message = Message(
        role="assistant", content="", is_compressed=False
    )

    @property
    def forward_synapse(self) -> "TextCompresssProtocol":
        return TextCompresssProtocol(
            context=self.extract_context(),
        )

    def extract_context(self) -> str:
        if self.user_message.is_compressed:
            return self.user_message.content
        elif self.assistant_message.is_compressed:
            return self.assistant_message.content
        else:
            raise ValueError("User or assistant messages must be marked as compressed")

    @property
    def original_messages(self) -> list[Message]:
        return [self.user_message, self.assistant_message]

    def get_compressed_messages(self, compressed_context: str) -> list[Message]:
        if self.user_message.is_compressed:
            return [
                Message(
                    role=self.user_message.role,
                    content=compressed_context,
                    is_compressed=True,
                ),
                self.assistant_message,
            ]
        elif self.assistant_message.is_compressed:
            return [
                self.user_message,
                Message(
                    role=self.assistant_message.role,
                    content=compressed_context,
                    is_compressed=True,
                ),
            ]
        else:
            raise ValueError("User or assistant messages must be marked as compressed")

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
