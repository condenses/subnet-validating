import bittensor as bt
from condenses_node_managing.client import AsyncOrchestratorClient
from text_compress_scoring.client import AsyncScoringClient
from restful_bittensor.client import AsyncRestfulBittensor
from condenses_synthesizing.client import AsyncSynthesizingClient
from condenses_validating.config import CONFIG
from .protocol import TextCompresssProtocol
import asyncio
from loguru import logger
from redis.asyncio import Redis
import traceback
from .redis_manager import RedisManager
from .response_processor import ResponseProcessor


class ScoringManager:
    def __init__(self, scoring_client: AsyncScoringClient, redis_manager: RedisManager):
        self.scoring_client = scoring_client
        self.redis_manager = redis_manager
        self.response_processor = ResponseProcessor()

    async def get_scores(
        self,
        responses: list[TextCompresssProtocol],
        synthetic_synapse: TextCompresssProtocol,
        uids: list[int],
    ) -> tuple[list[int], list[float]]:
        valid, invalid = self.response_processor.validate_responses(uids, responses)

        invalid_uids = [uid for uid, _, _ in invalid]
        invalid_scores = [0] * len(invalid)
        valid_uids = [uid for uid, _ in valid]
        valid_responses = [response for _, response in valid]

        if not valid_uids:
            return invalid_uids, invalid_scores

        logger.info(f"Validating {len(valid_uids)} UIDs")
        scored_counter = await self.redis_manager.get_scored_counter()
        valid_uids_to_score = [
            uid
            for uid in valid_uids
            if scored_counter.get(uid, 0)
            < CONFIG.validating.scoring_rate.max_scoring_count
        ]

        if valid_uids_to_score:
            logger.info(f"Scoring {len(valid_uids_to_score)} UIDs")
            original_user_message = synthetic_synapse.user_message
            valid_scores = await self.scoring_client.score_batch(
                original_user_message=original_user_message,
                batch_compressed_user_messages=[
                    response.compressed_context for response in valid_responses
                ],
            )
            await self.redis_manager.update_scoring_records(valid_uids_to_score, CONFIG)
        else:
            valid_uids = []
            valid_scores = []

        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores
        return final_uids, final_scores


class ValidatorCore:
    def __init__(self):
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
        self.dendrite = bt.Dendrite(wallet=self.wallet)
        self.should_exit = False

    async def get_synthetic(self) -> TextCompresssProtocol:
        user_message = await self.synthesizing.get_message()
        return TextCompresssProtocol(user_message=user_message)

    async def get_axons(self, uids: list[int]) -> list[bt.AxonInfo]:
        string_axons = await self.restful_bittensor.get_axons(uids=uids)
        return [bt.AxonInfo.from_string(axon) for axon in string_axons]

    async def forward(self):
        uids = await self.orchestrator.consume_rate_limits(
            uid=None,
            top_fraction=1.0,
            count=CONFIG.validating.batch_size,
            acceptable_consumed_rate=CONFIG.validating.synthetic_rate_limit,
        )
        synthetic_synapse = await self.get_synthetic()
        axons = await self.get_axons(uids)
        responses = await self.dendrite.forward(
            axons=axons,
            synapse=synthetic_synapse.forward_synapse,
            timeout=12,
        )
        uids, scores = await self.scoring_manager.get_scores(
            responses=responses,
            synthetic_synapse=synthetic_synapse,
            uids=uids,
        )

        futures = [
            self.orchestrator.update_stats(uid=uid, new_score=score)
            for uid, score in zip(uids, scores)
        ]
        await asyncio.gather(*futures)

    async def run(self) -> None:
        """Main validator loop"""
        logger.info("Starting validator loop.")
        await self.redis_manager.flush_db()

        while not self.should_exit:
            try:
                await self.forward()
            except Exception as e:
                logger.error(f"Forward error: {e}")
                traceback.print_exc()
            except KeyboardInterrupt:
                logger.success("Validator killed by keyboard interrupt.")
                exit()

    async def loop(self):
        while True:
            forwards = [self.forward() for _ in range(CONFIG.validating.batch_size)]
            await asyncio.gather(*forwards)
            await asyncio.sleep(CONFIG.validating.interval)


def start_loop():
    validator = ValidatorCore()
    asyncio.run(validator.loop())
