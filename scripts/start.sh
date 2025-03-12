#!/bin/bash

# End-to-End Setup Script for Condenses Validating

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Condenses Validating Setup Script ===${NC}"
echo -e "${YELLOW}This script will set up all components needed for the Condenses Validating subnet${NC}"

# Step 2: Collect required credentials
echo -e "\n${GREEN}Step 2: Collecting required credentials${NC}"
echo -e "${YELLOW}Please enter your Hugging Face token:${NC}"
read HF_TOKEN
update-env HF_TOKEN $HF_TOKEN

echo -e "${YELLOW}Please enter your Taostats API key (from https://dash.taostats.io/api-keys):${NC}"
read TAOSTATS_API_KEY
update-env TAOSTATS_API_KEY $TAOSTATS_API_KEY

echo -e "${YELLOW}Please enter your wallet name (default is 'default'):${NC}"
read WALLET_NAME
WALLET_NAME=${WALLET_NAME:-default}
update-env WALLET_NAME $WALLET_NAME

echo -e "${YELLOW}Please enter your wallet hotkey (default is 'default'):${NC}"
read WALLET_HOTKEY
WALLET_HOTKEY=${WALLET_HOTKEY:-default}
update-env WALLET_HOTKEY $WALLET_HOTKEY

echo -e "${YELLOW}Please enter your wallet path (default is '~/.bittensor/wallets'):${NC}"
read WALLET_PATH
WALLET_PATH=${WALLET_PATH:-~/.bittensor/wallets}
update-env WALLET_PATH $WALLET_PATH

# Step 3: Set up LLM Inference
echo -e "\n${GREEN}Step 3: Setting up LLM Inference${NC}"
export MODEL_NAME="meta-llama/Llama-3.1-8B-Instruct"
update-env VLLM_CONFIG__MODEL_NAME $MODEL_NAME

echo -e "${YELLOW}Do you want to set up self-hosted LLM inference? (requires A100 or H100 GPU) [y/N]:${NC}"
read SETUP_VLLM
if [[ $SETUP_VLLM == "y" || $SETUP_VLLM == "Y" ]]; then
    echo -e "${YELLOW}Enter the GPU index to use (default is 0):${NC}"
    read GPU_INDEX
    GPU_INDEX=${GPU_INDEX:-0}
    
    uv venv .vllm-venv
    source .vllm-venv/bin/activate
    uv pip install vllm
    export CUDA_VISIBLE_DEVICES=$GPU_INDEX
    pm2 start --name vllm "vllm serve $MODEL_NAME --enable-prefix-caching --enable-chunked-prefill"
    source .venv/bin/activate
    update-env VLLM_CONFIG__BASE_URL http://localhost:8000/v1
else
    echo -e "${YELLOW}Please enter your VLLM server address (e.g., http://localhost:8000/v1):${NC}"
    read VLLM_URL
    update-env VLLM_CONFIG__BASE_URL $VLLM_URL
fi

# Step 4: Start all services
echo -e "\n${GREEN}Step 4: Starting all services${NC}"

# Start Synthesizing
echo -e "${YELLOW}Starting Synthesizing service...${NC}"
pm2 start python --name "synthesizing" -- -m uvicorn condenses_synthesizing.server:app --host 127.0.0.1 --port 9100
update-env SYNTHESIZING__BASE_URL http://localhost:9100

# Start Node Managing
echo -e "${YELLOW}Starting Node Managing service...${NC}"
pm2 start python --name "node_managing" -- -m uvicorn condenses_node_managing.server:app --host 127.0.0.1 --port 9101
update-env NODE_MANAGING__BASE_URL http://localhost:9101

# Start Scoring
echo -e "${YELLOW}Starting Scoring service...${NC}"
export CUDA_VISIBLE_DEVICES=${GPU_INDEX:-0}
pm2 start python --name "scoring" -- -m uvicorn text_compress_scoring.server:app --host 127.0.0.1 --port 9102
update-env SCORING__BASE_URL http://localhost:9102

# Start Sidecar Bittensor
echo -e "${YELLOW}Starting Sidecar Bittensor service...${NC}"
pm2 start python --name "sidecar-bittensor" -- -m uvicorn sidecar_bittensor.server:app --host 127.0.0.1 --port 9103
update-env SIDECAR_BITTENSOR__BASE_URL http://localhost:9103

# Start Validating
echo -e "${YELLOW}Starting Validating service...${NC}"
pm2 start --name "validating" --interpreter python "condenses-validating"

# Step 5: Start Log Viewer
echo -e "\n${GREEN}Step 5: Starting Log Viewer${NC}"
echo -e "${YELLOW}Do you want to start the log viewer now? [y/N]:${NC}"
read START_LOG_VIEWER
if [[ $START_LOG_VIEWER == "y" || $START_LOG_VIEWER == "Y" ]]; then
    python condenses_validating/log_viewer.py
fi

echo -e "\n${GREEN}Setup complete! All services are now running.${NC}"
echo -e "${YELLOW}You can view logs using: pm2 logs${NC}"
echo -e "${YELLOW}You can start the log viewer anytime with: python condenses_validating/log_viewer.py${NC}"