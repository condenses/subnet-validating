import bittensor as bt
from condenses_node_managing.client import AsyncOrchestratorClient
from text_compress_scoring.client import AsyncScoringClient
from restful_bittensor.client import AsyncRestfulBittensor
from condenses_synthesizing.client import AsyncSynthesizingClient
from condenses_validating.config import CONFIG
from .protocol import TextCompressProtocol
import asyncio
from loguru import logger
from redis.asyncio import Redis
import traceback
from .redis_manager import RedisManager
from .response_processor import ResponseProcessor
import tiktoken


class ScoringManager:
    def __init__(self, scoring_client: AsyncScoringClient, redis_manager: RedisManager):
        self.scoring_client = scoring_client
        self.redis_manager = redis_manager
        self.response_processor = ResponseProcessor()
        logger.info("ScoringManager initialized")

    async def get_scores(
        self,
        responses: list[TextCompressProtocol],
        synthetic_synapse: TextCompressProtocol,
        uids: list[int],
    ) -> tuple[list[int], list[float]]:
        logger.info(
            f"[{synthetic_synapse.id}] Processing responses from {len(uids)} UIDs"
        )
        valid, invalid = self.response_processor.validate_responses(
            uids, responses, synthetic_synapse
        )

        invalid_uids = [uid for uid, _, _ in invalid]
        invalid_scores = [0] * len(invalid)
        valid_uids = [uid for uid, _ in valid]
        valid_responses = [response for _, response in valid]

        if not valid_uids:
            logger.warning("No valid responses received")
            return invalid_uids, invalid_scores

        logger.info(f"[{synthetic_synapse.id}] Validating {len(valid_uids)} UIDs")
        scored_counter = await self.redis_manager.get_scored_counter()
        valid_uids_to_score = [
            uid
            for uid in valid_uids
            if scored_counter.get(uid, 0)
            < CONFIG.validating.scoring_rate.max_scoring_count
        ]

        if valid_uids_to_score:
            logger.info(
                f"[{synthetic_synapse.id}] Scoring {len(valid_uids_to_score)} UIDs"
            )
            original_user_message = synthetic_synapse.user_message
            valid_scores = await self.scoring_client.score_batch(
                original_user_message=original_user_message,
                batch_compressed_user_messages=[
                    response.compressed_context for response in valid_responses
                ],
            )
            logger.debug(f"[{synthetic_synapse.id}] Received scores: {valid_scores}")
            valid_scores = [
                score * 0.8 + (1 - valid_responses.compress_rate) * 0.2
                for score, valid_responses in zip(valid_scores, valid_responses)
            ]
            await self.redis_manager.update_scoring_records(valid_uids_to_score, CONFIG)
            logger.info(f"[{synthetic_synapse.id}] Updated scoring records in Redis")
        else:
            logger.warning(f"[{synthetic_synapse.id}] No UIDs eligible for scoring")
            valid_uids = []
            valid_scores = []

        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores
        logger.info(
            f"[{synthetic_synapse.id}] Final results - UIDs: {len(final_uids)}, Scores: {len(final_scores)}"
        )
        return final_uids, final_scores


class ValidatorCore:
    def __init__(self):
        logger.info("Initializing ValidatorCore")
        self.redis_client = Redis(
            host=CONFIG.redis.host, port=CONFIG.redis.port, db=CONFIG.redis.db
        )
        self.redis_manager = RedisManager(self.redis_client)
        self.orchestrator = AsyncOrchestratorClient(CONFIG.orchestrator.base_url)
        self.scoring_client = AsyncScoringClient(CONFIG.scoring.base_url)
        self.restful_bittensor = AsyncRestfulBittensor(CONFIG.restful.base_url)
        self.synthesizing = AsyncSynthesizingClient(CONFIG.synthesizing.base_url)
        self.scoring_manager = ScoringManager(self.scoring_client, self.redis_manager)

        self.wallet = bt.wallet(
            path=CONFIG.wallet.path,
            name=CONFIG.wallet.name,
            hotkey=CONFIG.wallet.hotkey,
        )
        logger.info(f"Wallet initialized: {self.wallet}")
        self.dendrite = bt.Dendrite(wallet=self.wallet)
        self.should_exit = False
        logger.success("ValidatorCore initialization complete")

    async def get_synthetic(self) -> TextCompressProtocol:
        logger.debug("Requesting synthetic message")
        synth_response = await self.synthesizing.get_message()
        user_message = synth_response.user_message
        logger.debug(f"Received synthetic message: {user_message[:50]}...")
        return TextCompressProtocol(user_message=user_message)

    async def get_axons(self, uids: list[int]) -> list[bt.AxonInfo]:
        logger.debug(f"Fetching axon info for {len(uids)} UIDs")
        string_axons = await self.restful_bittensor.get_axons(uids=uids)
        axons = [bt.AxonInfo.from_string(axon) for axon in string_axons]
        logger.debug(f"Retrieved {len(axons)} axons")
        return axons

    async def forward(self):
        logger.info("Starting forward pass")
        uids = await self.orchestrator.consume_rate_limits(
            uid=None,
            top_fraction=1.0,
            count=CONFIG.validating.batch_size,
            acceptable_consumed_rate=CONFIG.validating.synthetic_rate_limit,
            timeout=12,
        )
        logger.info(f"Consumed rate limits for UIDs: {uids}")

        if not uids:
            logger.warning("No UIDs to forward to")
            return

        synthetic_synapse = await self.get_synthetic()
        logger.info(f"[{synthetic_synapse.id}] Processing synthetic message")
        axons = await self.get_axons(uids)

        logger.info(f"[{synthetic_synapse.id}] Forwarding to miners")
        forward_synapse = TextCompressProtocol(context=synthetic_synapse.user_message)
        responses = await self.dendrite.forward(
            axons=axons,
            synapse=forward_synapse,
            timeout=12,
        )
        logger.info(f"[{synthetic_synapse.id}] Received {len(responses)} responses")

        uids, scores = await self.scoring_manager.get_scores(
            responses=responses,
            synthetic_synapse=synthetic_synapse,
            uids=uids,
        )
        logger.info(f"[{synthetic_synapse.id}] UIDs: {uids}; Scores: {scores}")

        logger.info(f"[{synthetic_synapse.id}] Updating stats")
        futures = [
            self.orchestrator.update_stats(uid=uid, new_score=score)
            for uid, score in zip(uids, scores)
        ]
        await asyncio.gather(*futures)
        logger.success(f"[{synthetic_synapse.id}] Forward pass completed")

    async def run(self) -> None:
        """Main validator loop"""
        logger.info("Starting validator loop.")
        await self.redis_manager.flush_db()
        logger.info("Redis DB flushed")

        while not self.should_exit:
            try:
                await self.forward()
                await asyncio.sleep(8)
            except Exception as e:
                logger.error(f"Forward error: {e}")
                traceback.print_exc()
            except KeyboardInterrupt:
                logger.success("Validator killed by keyboard interrupt.")
                exit()


def start_loop():
    logger.info("Initializing validator")
    validator = ValidatorCore()
    logger.info("Starting validator loop")
    asyncio.run(validator.run())
