uv venv .vllm-venv
. .vllm-venv/bin/activate
uv pip install vllm
pm2 del vllm
pm2 start --name vllm "vllm serve $MODEL_NAME --enable-prefix-caching --enable-chunked-prefill"
. .venv/bin/activate
update-env VLLM_CONFIG__MODEL_NAME $MODEL_NAME