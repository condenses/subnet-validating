from .protocol import TextCompressProtocol
from typing import List, Tuple
from loguru import logger
import tiktoken
from .log_processor import ForwardLog


class ResponseProcessor:
    """Handles processing and validation of miner responses"""

    encoding = tiktoken.encoding_for_model("gpt-4o")

    async def validate_responses(
        self,
        uids: List[int],
        responses: List[TextCompressProtocol],
        ground_truth_synapse: TextCompressProtocol,
        forward_uuid: str,
        log: ForwardLog,
    ) -> Tuple[
        List[Tuple[int, TextCompressProtocol]],
        List[Tuple[int, TextCompressProtocol, str]],
    ]:
        valid = []
        invalid = []

        for uid, response in zip(uids, responses):
            if response and response.is_success and response.verify():
                valid.append((uid, response))
                original_tokens = self.encoding.encode(
                    ground_truth_synapse.user_message
                )
                compressed_tokens = self.encoding.encode(response.compressed_context)
                compress_rate = len(compressed_tokens) / len(original_tokens)
                log.add_log(
                    forward_uuid,
                    f"Valid response - {uid} - {response.dendrite.process_time}s - Compress rate: {compress_rate}",
                )
            else:
                invalid_reason = ""
                if not response:
                    invalid_reason = "no_response"
                elif not response.is_success:
                    invalid_reason = "not_successful"
                elif not response.verify():
                    invalid_reason = "verification_failed"

                invalid.append((uid, response, invalid_reason))
                log.add_log(
                    forward_uuid,
                    f"Invalid response - {uid} - {response.dendrite.process_time if response else 0}s - Reason: {invalid_reason}",
                )

        return valid, invalid
