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
from pydantic import BaseModel
import httpx
from .secured_headers import get_headers
from .score_utils import ScoringManager, ScoringBatchLog


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
        self.wallet = bt.Wallet(
            path=CONFIG.wallet_path,
            name=CONFIG.wallet_name,
            hotkey=CONFIG.wallet_hotkey,
        )
        logger.info(f"Wallet initialized: {self.wallet}")
        self.dendrite = bt.Dendrite(wallet=self.wallet)
        self.should_exit = False
        self.animation_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.animation_idx = 0
        logger.success("ValidatorCore initialization complete")
        self.owner_server = httpx.AsyncClient(
            base_url=CONFIG.owner_server.base_url,
        )

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
        await self.redis_manager.add_log(forward_uuid, "Starting forward pass")
        try:
            uids = await self.orchestrator.consume_rate_limits(
                uid=None,
                top_fraction=1.0,
                count=CONFIG.validating.batch_size,
                acceptable_consumed_rate=CONFIG.validating.synthetic_rate_limit,
                timeout=12,
            )
        except Exception as e:
            await self.redis_manager.add_log(
                forward_uuid, f"Error in consuming rate limits: {e}"
            )
            return
        try:
            synthetic_synapse = await self.get_synthetic()
        except Exception as e:
            await self.redis_manager.add_log(
                forward_uuid, f"Error in getting synthetic: {e}"
            )
            return
        await self.redis_manager.add_log(forward_uuid, f"Processing UIDs: {uids}")
        try:
            axons = await self.get_axons(uids)
        except Exception as e:
            await self.redis_manager.add_log(
                forward_uuid, f"Error in getting axons: {e}"
            )
            return
        await self.redis_manager.add_log(forward_uuid, f"Got {len(axons)} axons")

        try:
            forward_synapse = TextCompressProtocol(
                context=synthetic_synapse.user_message
            )
            responses = await self.dendrite.forward(
                axons=axons,
                synapse=forward_synapse,
                timeout=12,
            )
        except Exception as e:
            await self.redis_manager.add_log(forward_uuid, f"Error in forwarding: {e}")
            return
        await self.redis_manager.add_log(
            forward_uuid, f"Received {len(responses)} responses"
        )
        try:
            uids, scores, score_logs = await self.scoring_manager.get_scores(
                responses=responses,
                synthetic_synapse=synthetic_synapse,
                uids=uids,
                forward_uuid=forward_uuid,
            )
            try:
                await self.owner_server.post(
                    "/api/v1/scoring_batch",
                    json=score_logs,
                    headers=get_headers(),
                )
            except Exception as e:
                logger.error(f"Error in sending scoring batch to owner server: {e}")
        except Exception as e:
            await self.redis_manager.add_log(forward_uuid, f"Error in scoring: {e}")
            return
        await self.redis_manager.add_log(
            forward_uuid, f"Scored {len(scores)} responses"
        )
        try:
            futures = [
                self.orchestrator.update_stats(uid=uid, new_score=score)
                for uid, score in zip(uids, scores)
            ]
            await asyncio.gather(*futures)
        except Exception as e:
            await self.redis_manager.add_log(
                forward_uuid, f"Error in updating stats: {e}"
            )
            return
        await self.redis_manager.add_log(forward_uuid, "✓ Forward complete")

    async def run(self) -> None:
        """Main validator loop"""
        logger.info("Starting validator loop.")
        await self.redis_manager.flush_db()
        logger.info("Redis DB flushed")
        asyncio.create_task(self.periodically_set_weights())
        asyncio.create_task(self.animate_progress())

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
            try:
                uids, weights = await self.orchestrator.get_score_weights()
                result, msg = await self.restful_bittensor.set_weights(
                    uids=uids, weights=weights, netuid=47, version=99
                )
                if result:
                    await self.redis_manager.add_log(
                        "set_weights",
                        f"Updated weights at {datetime.now()}\n"
                        f"Top UIDs: {uids[:5]}\n"
                        f"Top Weights: {weights[:5]}\n"
                        f"{msg}",
                    )
                else:
                    await self.redis_manager.add_log(
                        "set_weights",
                        f"Failed to update weights: {msg}",
                    )
            except Exception as e:
                logger.error(f"Weight update error: {e}")
            await asyncio.sleep(60)

    async def animate_progress(self):
        """Displays an animation to indicate the validator is running"""
        while not self.should_exit:
            animation_char = self.animation_chars[self.animation_idx]
            print(f"\r{animation_char} Validator running...", end="", flush=True)
            self.animation_idx = (self.animation_idx + 1) % len(self.animation_chars)
            await asyncio.sleep(0.1)


def start_loop():
    logger.info("Initializing validator")
    validator = ValidatorCore()
    logger.info("Starting validator loop")
    asyncio.run(validator.run())
