from .protocol import TextCompressProtocol
from typing import List, Tuple
from loguru import logger
import tiktoken
from .config import CONFIG


class ResponseProcessor:
    """Handles processing and validation of miner responses"""

    encoding = tiktoken.encoding_for_model("gpt-4o")

    def get_compress_rate(
        self, response: TextCompressProtocol, ground_truth_context: str
    ) -> float:
        try:
            original_tokens = self.encoding.encode(ground_truth_context)
            compressed_tokens = self.encoding.encode(response.compressed_context)
            return len(compressed_tokens) / len(original_tokens)
        except Exception as e:
            logger.error(f"Error getting compress rate: {e}")
            raise e

    async def validate_responses(
        self,
        uids: List[int],
        responses: List[TextCompressProtocol],
        ground_truth_synapse: TextCompressProtocol,
    ) -> Tuple[
        List[Tuple[int, TextCompressProtocol]],
        List[Tuple[int, TextCompressProtocol, str]],
    ]:
        valid = []
        invalid = []

        for uid, response in zip(uids, responses):
            if (
                response
                and response.is_success
                and response.verify()
                and self.get_compress_rate(response, ground_truth_synapse.context)
                < CONFIG.validating.max_compress_rate
            ):
                valid.append((uid, response))
            else:
                invalid_reason = ""
                if not response:
                    invalid_reason = "no_response"
                elif not response.is_success:
                    invalid_reason = "not_successful"
                elif not response.verify():
                    invalid_reason = "verification_failed"
                elif (
                    self.get_compress_rate(response, ground_truth_synapse.context)
                    > CONFIG.validating.max_compress_rate
                ):
                    invalid_reason = "compress_rate_too_high"

                invalid.append((uid, response, invalid_reason))
        return valid, invalid
