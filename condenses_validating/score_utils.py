from text_compress_scoring.client import AsyncScoringClient
from condenses_validating.config import CONFIG
from .protocol import TextCompressProtocol
from loguru import logger
from .redis_manager import RedisManager
from .response_processor import ResponseProcessor
from pydantic import BaseModel
import re
import tiktoken


def SCORE_ENSEMBLE(
    raw_scores: list[float],
    compress_rates: list[float],
    differentiate_scores: list[float],
) -> list[float]:
    return [
        score * 0.7 + (compress_rate * 0.2 + differentiate_score * 0.1) * score
        for score, compress_rate, differentiate_score in zip(
            raw_scores, compress_rates, differentiate_scores
        )
    ]


def extract_words(text: str) -> list[str]:
    """
    Extract words from the text.
    """
    return re.findall(r"\b\w+\b", text.lower())


def word_edit_distance(text1: str, text2: str) -> int:
    """
    Calculate the word-level edit distance between two texts.
    Operations: insert word, delete word, substitute word
    """
    words1 = extract_words(text1)
    words2 = extract_words(text2)

    m, n = len(words1), len(words2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if words1[i - 1] == words2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],  # Deletion
                    dp[i][j - 1],  # Insertion
                    dp[i - 1][j - 1],  # Substitution
                )

    return dp[m][n]


def word_edit_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity score based on word edit distance.
    Returns a value between 0 and 1, where 1 means identical texts.
    """
    distance = word_edit_distance(text1, text2)
    words1 = extract_words(text1)
    words2 = extract_words(text2)
    max_length = max(len(words1), len(words2))
    return 1 - (distance / max_length) if max_length > 0 else 1.0


def get_text_differentiate_score(texts: list[str]) -> list[float]:
    """
    Get the differentiate score of the text.
    - Input: list of texts
    - Output: list of scores

    For each text, calculates how different it is from all other texts in the list.
    Returns a list of scores between 0 and 1, where:
    - Higher scores indicate more unique/different texts
    - Lower scores indicate more similar/redundant texts
    """
    if not texts:
        return []

    if len(texts) == 1:
        return [1.0]

    n = len(texts)
    scores = []

    for i, text1 in enumerate(texts):
        # Calculate average difference (1 - similarity) from all other texts
        total_diff = 0.0
        for j, text2 in enumerate(texts):
            if i != j:
                similarity = word_edit_similarity(text1, text2)
                difference = 1.0 - similarity
                total_diff += difference

        # Average difference score for this text
        avg_diff = total_diff / (n - 1)
        scores.append(avg_diff)

    return scores


class ScoringBatchLog(BaseModel):
    invalid_uids: list[int] = []
    valid_uids: list[int] = []
    uids_to_score: list[int] = []
    compress_rates: list[float] = []
    differentiate_scores: list[float] = []
    raw_scores: list[float] = []
    final_scores: list[float] = []


class ScoringManager:
    def __init__(self, scoring_client: AsyncScoringClient, redis_manager: RedisManager):
        self.scoring_client = scoring_client
        self.redis_manager = redis_manager
        self.response_processor = ResponseProcessor()
        self.tiktoken = tiktoken.encoding_for_model("gpt-4o")
        logger.info("ScoringManager initialized")

    def calculate_compress_rates(
        self, ref_text: str, compressed_texts: list[str]
    ) -> list[float]:
        ref_tokens = len(self.tiktoken.encode(ref_text))
        compressed_tokens = [
            len(self.tiktoken.encode(text)) for text in compressed_texts
        ]
        return [1 - token_count / ref_tokens for token_count in compressed_tokens]

    async def get_scores(
        self,
        responses: list[TextCompressProtocol],
        synthetic_synapse: TextCompressProtocol,
        uids: list[int],
        forward_uuid: str,
    ) -> tuple[list[int], list[float], ScoringBatchLog]:
        score_logs = ScoringBatchLog(
            invalid_uids=[],
            valid_uids=[],
            uids_to_score=[],
        )
        await self.redis_manager.add_log(
            forward_uuid, f"Processing responses from {len(uids)} UIDs"
        )
        valid, invalid = await self.response_processor.validate_responses(
            uids, responses, synthetic_synapse
        )

        invalid_uids = [uid for uid, _, _ in invalid]
        invalid_scores = [0] * len(invalid)
        valid_uids = [uid for uid, _ in valid]
        valid_responses_dict = {uid: response for uid, response in valid}

        score_logs.invalid_uids = invalid_uids
        score_logs.valid_uids = valid_uids

        if not valid_uids:
            await self.redis_manager.add_log(
                forward_uuid, "Warning: No valid responses received"
            )
            return invalid_uids, invalid_scores, score_logs

        await self.redis_manager.add_log(
            forward_uuid, f"Validating {len(valid_uids)} UIDs"
        )
        scored_counter = await self.redis_manager.get_scored_counter()
        uids_to_score = [
            uid
            for uid in valid_uids
            if scored_counter.get(uid, 0)
            < CONFIG.validating.scoring_rate.max_scoring_count
        ]
        score_logs.uids_to_score = uids_to_score

        if uids_to_score:
            await self.redis_manager.add_log(
                forward_uuid, f"Scoring {len(uids_to_score)} UIDs"
            )
            # Get responses only for UIDs that need scoring
            responses_to_score = [valid_responses_dict[uid] for uid in uids_to_score]

            original_user_message = synthetic_synapse.user_message
            scored_responses = await self.scoring_client.score_batch(
                original_user_message=original_user_message,
                batch_compressed_user_messages=[
                    response.compressed_context for response in responses_to_score
                ],
                timeout=360,
            )
            await self.redis_manager.add_log(
                forward_uuid, f"Received scores: {scored_responses}"
            )

            compress_rates = self.calculate_compress_rates(
                original_user_message,
                [response.compressed_context for response in responses_to_score],
            )
            await self.redis_manager.add_log(
                forward_uuid, f"Compress rates: {compress_rates}"
            )

            differentiate_scores = get_text_differentiate_score(
                [response.compressed_context for response in responses_to_score]
            )
            await self.redis_manager.add_log(
                forward_uuid, f"Differentiate scores: {differentiate_scores}"
            )

            score_logs.compress_rates = compress_rates
            score_logs.differentiate_scores = differentiate_scores
            score_logs.raw_scores = scored_responses

            final_scored_responses = SCORE_ENSEMBLE(
                scored_responses, compress_rates, differentiate_scores
            )
            await self.redis_manager.add_log(
                forward_uuid, f"Final scores: {final_scored_responses}"
            )
            score_logs.final_scores = final_scored_responses

            # Create a mapping of scores for valid UIDs
            valid_scores_dict = {uid: 0.0 for uid in valid_uids}  # Initialize all to 0
            for uid, score in zip(uids_to_score, final_scored_responses):
                valid_scores_dict[uid] = score

            valid_scores = [valid_scores_dict[uid] for uid in valid_uids]
            await self.redis_manager.update_scoring_records(uids_to_score, CONFIG)
            await self.redis_manager.add_log(
                forward_uuid, "Updated scoring records in Redis"
            )
        else:
            await self.redis_manager.add_log(
                forward_uuid, "Warning: No UIDs eligible for scoring"
            )
            valid_uids = []
            valid_scores = []

        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores

        await self.redis_manager.add_log(
            forward_uuid,
            f"Final results - UIDs: {len(final_uids)}, Scores: {len(final_scores)}",
        )
        return final_uids, final_scores, score_logs.model_dump()
