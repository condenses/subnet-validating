<br /><br />
<div align="center">
  <h1 align="center">condenses-validating</h1>
  <h4 align="center"> Orchestrating validating process that connects with other condenses services</div>

$$
S_i = 0.7r_i + 0.2r_ic_i + 0.1r_id_i
$$

The weights in the formula are:
- 70% weight on the raw - llm preference score
- 20% weight on the compression rate's contribution
- 10% weight on the differentiation score's contribution

The compression rate and differentiation score act as multipliers that can boost the raw score, where:
- $c_i \in [0,1]$ represents how well the text was compressed
- $d_i \in [0,1]$ represents how unique/different the response is from others


## Installation

To install the necessary components, run the following commands:

```bash
pip install git+https://github.com/condenses/condenses-validating.git
pip install uv
uv venv
. .venv/bin/activate
uv sync --prerelease=allow
. scripts/install_redis.sh
```

## Quick Start

### 1. Setup LLM Inference

#### 1.1 Self-hosted LLM Inference

*Requires A100 or H100 GPU*
- Get access to the model from https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct then obtain a token from huggingface
```bash
export MODEL_NAME="meta-llama/Llama-3.1-8B-Instruct"
export HF_TOKEN=your_huggingface_token
uv venv .vllm-venv
. .vllm-venv/bin/activate
uv pip install vllm
export CUDA_VISIBLE_DEVICES=0 # Change to your GPU index
pm2 start --name vllm "vllm serve $MODEL_NAME --enable-prefix-caching --enable-chunked-prefill"
. .venv/bin/activate
update-env VLLM__BASE_URL http://localhost:8000 # Change to your VLLM server address, default is localhost:8000 if you serve vllm on the same machine
```

### 2. Synthesizing

**Role**: Serve an endpoint that can synthesize the user message from public dataset.

```bash
update-env HF_TOKEN your_huggingface_token
pm2 start python --name "synthesizing" -- -m uvicorn condenses_synthesizing.server:app --host 127.0.0.1 --port 9100
```

### 3. Node Managing

**Role**: Manage credit & "validator -> miner" rate limit. Orchestrating UIDs for synthetic validation.

```bash
pm2 start python --name "node_managing" -- -m uvicorn condenses_node_managing.server:app --host 127.0.0.1 --port 9101
```

### 4. Scoring

**Role**: Receive original message and compressed messages, run scoring algorithm and return the score.

```bash
update-env VLLM_CONFIG__MODEL_NAME $MODEL_NAME
export CUDA_VISIBLE_DEVICES=0 # Change to your GPU index
pm2 start python --name "scoring" -- -m uvicorn text_compress_scoring.server:app --host 127.0.0.1 --port 9102
```

### 5. Sidecar Bittensor

**Role**: Dedicated process for auto-sync metagraph and chain functions: get-axon, set-weights, get-chain data

```bash
update-env WALLET_NAME default
update-env WALLET_HOTKEY default
update-env WALLET_PATH ~/.bittensor/wallets
pm2 start python --name "sidecar-bittensor" -- -m uvicorn sidecar_bittensor.server:app --host 127.0.0.1 --port 9103
```

### 6. Validating

**Role**: Main process that orchestrates the validating process.

```bash
update-env SYNTHESIZING__BASE_URL http://localhost:9100
update-env NODE_MANAGING__BASE_URL http://localhost:9101
update-env SCORING__BASE_URL http://localhost:9102
update-env SIDECAR_BITTENSOR__BASE_URL http://localhost:9103
pm2 start --name "validating" "condenses-validating"
```

### 7. Log Viewer

**Role**: A console frontend to view the logs of the validating process. It helps to differentiate the logs from: `set_weights|running_logs|finished_logs`

```bash
python condenses_validating/log_viewer.py
```

![log-viewer](assets/log-viewer.png)

## Related Repositories

- [Subnet Node Managing](https://github.com/condenses/subnet-node-managing)
- [Text Compress Scoring](https://github.com/condenses/text-compress-scoring)
- [Sidecar Bittensor](https://github.com/condenses/sidecar-bittensor)
- [Subnet Synthesizing](https://github.com/condenses/subnet-synthesizing)
