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
from .log_processor import ForwardLog
import uuid
from datetime import datetime


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
        log: ForwardLog,
        forward_uuid: str,
    ) -> tuple[list[int], list[float]]:
        await log.add_log(forward_uuid, f"Processing responses from {len(uids)} UIDs")
        valid, invalid = await self.response_processor.validate_responses(
            uids, responses, synthetic_synapse
        )

        invalid_uids = [uid for uid, _, _ in invalid]
        invalid_scores = [0] * len(invalid)
        valid_uids = [uid for uid, _ in valid]
        valid_responses = [response for _, response in valid]

        if not valid_uids:
            await log.add_log(forward_uuid, "Warning: No valid responses received")
            return invalid_uids, invalid_scores

        await log.add_log(forward_uuid, f"Validating {len(valid_uids)} UIDs")
        scored_counter = await self.redis_manager.get_scored_counter()
        valid_uids_to_score = [
            uid
            for uid in valid_uids
            if scored_counter.get(uid, 0)
            < CONFIG.validating.scoring_rate.max_scoring_count
        ]

        if valid_uids_to_score:
            await log.add_log(forward_uuid, f"Scoring {len(valid_uids_to_score)} UIDs")
            original_user_message = synthetic_synapse.user_message
            valid_scores = await self.scoring_client.score_batch(
                original_user_message=original_user_message,
                batch_compressed_user_messages=[
                    response.compressed_context for response in valid_responses
                ],
                timeout=360,
            )
            await log.add_log(forward_uuid, f"Received scores: {valid_scores}")
            valid_scores = [
                score * 0.8 + (1 - valid_responses.compress_rate) * 0.2
                for score, valid_responses in zip(valid_scores, valid_responses)
            ]
            await self.redis_manager.update_scoring_records(valid_uids_to_score, CONFIG)
            await log.add_log(forward_uuid, "Updated scoring records in Redis")
        else:
            await log.add_log(forward_uuid, "Warning: No UIDs eligible for scoring")
            valid_uids = []
            valid_scores = []

        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores
        await log.add_log(
            forward_uuid,
            f"Final results - UIDs: {len(final_uids)}, Scores: {len(final_scores)}",
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
        self.restful_bittensor = AsyncRestfulBittensor(
            CONFIG.restful_bittensor.base_url
        )
        self.synthesizing = AsyncSynthesizingClient(CONFIG.synthesizing.base_url)
        self.scoring_manager = ScoringManager(self.scoring_client, self.redis_manager)
        self.forward_log = ForwardLog(redis_client=self.redis_client)

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
        synth_response = await self.synthesizing.get_message()
        user_message = synth_response.user_message
        return TextCompressProtocol(user_message=user_message)

    async def get_axons(self, uids: list[int]) -> list[bt.AxonInfo]:
        string_axons = await self.restful_bittensor.get_axons(uids=uids)
        axons = [bt.AxonInfo.from_string(axon) for axon in string_axons]
        return axons

    async def forward(self):
        forward_uuid = str(uuid.uuid4())
        async with self.forward_log as log:
            await log.add_log(forward_uuid, "Starting forward pass")
            uids = await self.orchestrator.consume_rate_limits(
                uid=None,
                top_fraction=1.0,
                count=CONFIG.validating.batch_size,
                acceptable_consumed_rate=CONFIG.validating.synthetic_rate_limit,
                timeout=12,
            )
            try:
                synthetic_synapse = await self.get_synthetic()
            except Exception as e:
                await log.add_log(forward_uuid, f"Error in getting synthetic: {e}")
                return
            await log.add_log(forward_uuid, f"Processing UIDs: {uids}")
            try:
                axons = await self.get_axons(uids)
            except Exception as e:
                await log.add_log(forward_uuid, f"Error in getting axons: {e}")
                return
            await log.add_log(forward_uuid, f"Got {len(axons)} axons")

            forward_synapse = TextCompressProtocol(
                context=synthetic_synapse.user_message
            )
            responses = await self.dendrite.forward(
                axons=axons,
                synapse=forward_synapse,
                timeout=12,
            )
            await log.add_log(forward_uuid, f"Received {len(responses)} responses")
            try:
                uids, scores = await self.scoring_manager.get_scores(
                    responses=responses,
                    synthetic_synapse=synthetic_synapse,
                    uids=uids,
                    log=log,
                    forward_uuid=forward_uuid,
                )
            except Exception as e:
                await log.add_log(forward_uuid, f"Error in scoring: {e}")
                return
            await log.add_log(forward_uuid, f"Scored {len(scores)} responses")

            futures = [
                self.orchestrator.update_stats(uid=uid, new_score=score)
                for uid, score in zip(uids, scores)
            ]
            await asyncio.gather(*futures)
            await log.add_log(forward_uuid, "✓ Forward complete")

    async def run(self) -> None:
        """Main validator loop"""
        logger.info("Starting validator loop.")
        await self.redis_manager.flush_db()
        logger.info("Redis DB flushed")
        asyncio.create_task(self.periodically_set_weights())

        while not self.should_exit:
            try:
                concurrent_forwards = [
                    self.forward() for _ in range(CONFIG.validating.concurrent_forward)
                ]
                await asyncio.gather(*concurrent_forwards)
                await asyncio.sleep(8)
            except Exception as e:
                logger.error(f"Forward error: {e}")
                traceback.print_exc()
            except KeyboardInterrupt:
                logger.success("Validator killed by keyboard interrupt.")
                exit()

    async def periodically_set_weights(self):
        while not self.should_exit:
            async with self.forward_log as log:
                try:
                    last_update = await self.restful_bittensor.get_last_update()
                    await log.add_log("set_weights", f"last_update: {last_update}")
                    uids, weights = await self.orchestrator.get_score_weights()
                    await log.add_log(
                        "set_weights",
                        f"uids: {uids[:10]}...\nweights: {weights[:10]}...",
                    )
                except Exception as e:
                    await log.add_log("set_weights", f"Error in getting weights: {e}")
                    continue
                try:
                    result, msg = await self.restful_bittensor.set_weights(
                        uids=uids, weights=weights
                    )
                    await log.add_log(
                        "set_weights",
                        f"------{datetime.now()}------\n"
                        f"uids: {uids[:10]}...\n"
                        f"weights: {weights[:10]}...\n"
                        f"result: {result}\n"
                        f"msg: {msg}\n",
                    )
                except Exception as e:
                    await log.add_log("set_weights", f"Error in setting weights: {e}")
                    continue
            await asyncio.sleep(60)


def start_loop():
    logger.info("Initializing validator")
    validator = ValidatorCore()
    logger.info("Starting validator loop")
    asyncio.run(validator.run())
