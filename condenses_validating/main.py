import bittensor as bt
from condenses_node_managing.client import AsyncOrchestratorClient
from text_compress_scoring.client import AsyncScoringClient
from restful_bittensor.client import AsyncRestfulBittensor
from condenses_synthesizing.client import AsyncSynthesizingClient
from condenses_validating.config import CONFIG
from .protocol import TextCompresssProtocol
import asyncio


class Validator:
    def __init__(self):
        self.orchestrator = AsyncOrchestratorClient(CONFIG.orchestrator.base_url)
        self.scoring_client = AsyncScoringClient(CONFIG.scoring.base_url)
        self.restful = AsyncRestfulBittensor(CONFIG.restful.base_url)
        self.synthesizing = AsyncSynthesizingClient(CONFIG.synthesizing.base_url)
        self.wallet = bt.wallet(
            path=CONFIG.wallet.path,
            name=CONFIG.wallet.name,
            hotkey=CONFIG.wallet.hotkey,
        )
        self.dendrite = bt.Dendrite(
            wallet=self.wallet,
        )

    async def get_synthetic(self) -> TextCompresssProtocol:
        user_message, assistant_message = await self.synthesizing.get_synthetic()
        return TextCompresssProtocol(
            original_messages=[user_message, assistant_message],
        )

    async def get_axons(self, uids: list[int]) -> list[bt.AxonInfo]:
        string_axons = await self.restful.get_axons(uids=uids)
        return [bt.AxonInfo.from_string(axon) for axon in string_axons]

    async def forward(self):
        uids = await self.orchestrator.consume_rate_limits(
            uid=None,
            top_fraction=1.0,
            count=CONFIG.validating.batch_size,
            acceptable_consumed_rate=CONFIG.validating.synthetic_rate_limit,
        )
        synthetic_synapse = self.get_synthetic()
        axons = await self.get_axons(uids)
        responses: list[TextCompresssProtocol] = await self.dendrite.forward(
            axons=axons,
            synapse=synthetic_synapse.forward_synapse,
            timeout=12,
        )
        uids, scores = await self.get_scores(
            responses=responses,
            synthetic_synapse=synthetic_synapse,
            uids=uids,
        )
        futures = []
        for uid, score in zip(uids, scores):
            futures.append(
                self.orchestrator.update_stats(
                    uid=uid,
                    new_score=score,
                )
            )
        await asyncio.gather(*futures)

    async def get_scores(
        self,
        responses: list[TextCompresssProtocol],
        synthetic_synapse: TextCompresssProtocol,
        uids: list[int],
    ) -> tuple[list[int], list[float]]:
        invalid_uids, invalid_scores = [], []
        valid_uids, valid_responses = [], []
        for uid, response in zip(uids, responses):
            if not response or not response.verify():
                invalid_uids.append(uid)
                invalid_scores.append(0)
            else:
                valid_uids.append(uid)
                valid_responses.append(response)
        original_messages = synthetic_synapse.original_messages
        batch_compressed_messages = [
            synthetic_synapse.get_compressed_messages(response.compressed_context)
            for response in valid_responses
        ]
        valid_scores = await self.scoring_client.score_batch(
            original_messages=original_messages,
            batch_compressed_messages=batch_compressed_messages,
        )
        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores
        return final_uids, final_scores

    async def loop(self):
        while True:
            forwards = [self.forward() for _ in range(CONFIG.validating.batch_size)]
            await asyncio.gather(*forwards)
            await asyncio.sleep(CONFIG.validating.interval)


def start_loop():
    validator = Validator()
    asyncio.run(validator.loop())
