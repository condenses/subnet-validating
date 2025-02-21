uv venv .vllm-venv
. .vllm-venv/bin/activate
uv pip install vllm
pm2 start --name vllm "vllm serve mistralai/Mistral-Small-24B-Instruct-2501 --enable-prefix-caching --enable-chunked-prefill"
. .venv/bin/activate