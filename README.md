
<br /><br />
<div align="center">
  <h1 align="center">condenses-validating</h1>
  <h4 align="center"> Orchestrating validating process that connects with other condenses services</div>

## Installation

```bash
pip install git+https://github.com/condenses/condenses-validating.git
pip install uv
uv venv
. .venv/bin/activate
uv sync --prerelease=allow
. scripts/install_redis.sh
```

## Quick Start

1. Install and run vLLM

```bash
export HF_TOKEN=your_huggingface_token
./scripts/install_vllm.sh
```

2. Synthesizing

- Run

```bash
echo "HF_TOKEN=your_huggingface_token" >> .synthesizing.env
pm2 start python --name "synthesizing" -- -m uvicorn condenses_synthesizing.server:app --host 127.0.0.1 --port 9100
```

3. Node Managing

- Run:

```bash
pm2 start python --name "node_managing" -- -m uvicorn condenses_node_managing.server:app --host 127.0.0.1 --port 9101
```

4. Scoring

- Environment variables:

```bash
echo "VLLM__BASE_URL=http://localhost:8000" >> .env
```

- Run:

```bash
pm2 start python --name "scoring" -- -m uvicorn text_compress_scoring.server:app --host 127.0.0.1 --port 9102
```

5. Restful Bittensor

```bash
pm2 start python --name "restful_bittensor" -- -m uvicorn restful_bittensor.server:app --host 127.0.0.1 --port 9103
```

6. Validating

- Environment variables:

```bash
echo "SYNTHESIZING__BASE_URL=http://localhost:9100" >> .env
echo "NODE_MANAGING__BASE_URL=http://localhost:9101" >> .env
echo "SCORING__BASE_URL=http://localhost:9102" >> .env
echo "RESTFUL_BITTENSOR__BASE_URL=http://localhost:9103" >> .env
echo "WALLET_NAME=default" >> .env
echo "WALLET_HOTKEY=default" >> .env
echo "WALLET_PATH=~/.bittensor/wallets" >> .env
```

- Run

```bash
pm2 start --name "validating" "condenses-validating"
```


