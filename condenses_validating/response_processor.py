from .protocol import TextCompressProtocol
from typing import List, Tuple
from loguru import logger


class ResponseProcessor:
    """Handles processing and validation of miner responses"""

    @staticmethod
    def validate_responses(
        uids: List[int], responses: List[TextCompressProtocol]
    ) -> Tuple[
        List[Tuple[int, TextCompressProtocol]],
        List[Tuple[int, TextCompressProtocol, str]],
    ]:
        valid = []
        invalid = []

        for uid, response in zip(uids, responses):
            if response and response.is_success and response.verify():
                valid.append((uid, response))
                logger.info(
                    f"Valid response - {uid} - {response.dendrite.process_time}s"
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
                logger.info(
                    f"Invalid response - {uid} - {response.dendrite.process_time if response else 0}s - Reason: {invalid_reason}"
                )

        return valid, invalid
