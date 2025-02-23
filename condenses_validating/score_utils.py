from text_compress_scoring.client import AsyncScoringClient
from condenses_validating.config import CONFIG
from .protocol import TextCompressProtocol
from loguru import logger
from .redis_manager import RedisManager
from .response_processor import ResponseProcessor
from pydantic import BaseModel, Field
import re
import tiktoken
from datetime import datetime


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


class ResponseData(BaseModel):
    uid: int
    compressed_text: str
    compress_rate: float | None = None
    differentiate_score: float | None = None
    raw_score: float | None = None
    final_score: float | None = None


class ScoringBatchLog(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    original_user_message: str = ""
    invalid_responses: list[ResponseData] = []
    valid_responses: list[ResponseData] = []
    scored_responses: list[ResponseData] = []

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        # Convert datetime to specified format string
        data["timestamp"] = data["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        return data


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
    ) -> tuple[list[int], list[float], dict]:
        score_logs = ScoringBatchLog(
            original_user_message=synthetic_synapse.user_message
        )

        await self.redis_manager.add_log(
            forward_uuid, f"Processing responses from {len(uids)} UIDs"
        )
        valid, invalid = await self.response_processor.validate_responses(
            uids, responses, synthetic_synapse
        )

        # Process invalid responses
        score_logs.invalid_responses = [
            ResponseData(
                uid=uid,
                compressed_text=response.compressed_context if response else "",
                final_score=0.0,
            )
            for uid, response, _ in invalid
        ]

        # Process valid responses
        valid_responses = [
            ResponseData(uid=uid, compressed_text=response.compressed_context)
            for uid, response in valid
        ]
        score_logs.valid_responses = valid_responses

        if not valid_responses:
            await self.redis_manager.add_log(
                forward_uuid, "Warning: No valid responses received"
            )
            return (
                [r.uid for r in score_logs.invalid_responses],
                [r.final_score for r in score_logs.invalid_responses],
                score_logs.model_dump(),
            )

        # Filter responses that need scoring
        scored_counter = await self.redis_manager.get_scored_counter()
        responses_to_score = [
            response
            for response in valid_responses
            if scored_counter.get(response.uid, 0)
            < CONFIG.validating.scoring_rate.max_scoring_count
        ]

        if responses_to_score:
            await self.redis_manager.add_log(
                forward_uuid, f"Scoring {len(responses_to_score)} UIDs"
            )

            # Get scores and rates
            raw_scores = await self.scoring_client.score_batch(
                original_user_message=score_logs.original_user_message,
                batch_compressed_user_messages=[
                    r.compressed_text for r in responses_to_score
                ],
                timeout=360,
            )

            compress_rates = self.calculate_compress_rates(
                score_logs.original_user_message,
                [r.compressed_text for r in responses_to_score],
            )

            differentiate_scores = get_text_differentiate_score(
                [r.compressed_text for r in responses_to_score]
            )

            final_scores = SCORE_ENSEMBLE(
                raw_scores, compress_rates, differentiate_scores
            )

            # Update response data with scores
            for response, raw_score, compress_rate, diff_score, final_score in zip(
                responses_to_score,
                raw_scores,
                compress_rates,
                differentiate_scores,
                final_scores,
            ):
                response.raw_score = raw_score
                response.compress_rate = compress_rate
                response.differentiate_score = diff_score
                response.final_score = final_score

            score_logs.scored_responses = responses_to_score
            await self.redis_manager.update_scoring_records(
                [r.uid for r in responses_to_score], CONFIG
            )

        # Prepare final results
        all_responses = {r.uid: r for r in score_logs.invalid_responses}
        all_responses.update({r.uid: r for r in valid_responses})

        final_uids = list(all_responses.keys())
        final_scores = [all_responses[uid].final_score or 0.0 for uid in final_uids]

        return final_uids, final_scores, score_logs.model_dump()
