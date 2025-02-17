import bittensor as bt
from condenses_node_managing.client import OrchestratorClient
from text_compress_scoring.client import ScoringClient
from condenses_validating.config import CONFIG
from .protocol import TextCompresssProtocol


class Validator:
    def __init__(self):
        self.orchestrator = OrchestratorClient(CONFIG.orchestrator.base_url)
        self.scoring_client = ScoringClient(CONFIG.scoring.base_url)
        self.wallet = bt.wallet(
            path=CONFIG.wallet.path,
            name=CONFIG.wallet.name,
            hotkey=CONFIG.wallet.hotkey,
        )
        self.dendrite = bt.Dendrite(
            wallet=self.wallet,
        )

    def get_synthetic(self) -> TextCompresssProtocol:
        pass

    def get_axons(self, uids: list[int]) -> list[bt.AxonInfo]:
        pass

    def forward(self):
        uids = self.orchestrator.check_rate_limits(
            uid=None, top_fraction=1.0, count=CONFIG.validating.batch_size
        )
        synthetic_synapse = self.get_synthetic()
        axons = self.get_axons(uids)
        responses: list[TextCompresssProtocol] = self.dendrite.forward(
            axons=axons,
            synapse=synthetic_synapse.forward_synapse,
            timeout=12,
        )

    def get_scores(
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
        valid_scores = self.scoring_client.score_batch(
            original_messages=original_messages,
            batch_compressed_messages=batch_compressed_messages,
        )
        final_uids = invalid_uids + valid_uids
        final_scores = invalid_scores + valid_scores
        return final_uids, final_scores

    def validate(self):
        pass
