import bittensor as bt
from .config import CONFIG
import time
from loguru import logger

WALLET = bt.Wallet(
    path=CONFIG.wallet_path,
    name=CONFIG.wallet_name,
    hotkey=CONFIG.wallet_hotkey,
)

logger.info(f"Wallet address: {WALLET.hotkey.ss58_address}")


def get_headers() -> dict:
    message = str(time.time_ns())
    signature = WALLET.hotkey.sign(message.encode())
    address = WALLET.hotkey.ss58_address
    return {
        "message": message,
        "signature": f"0x{signature.hex()}",
        "ss58_address": address,
        "Content-Type": "application/json",
    }


def verify_headers(headers: dict) -> bool:
    message = headers["message"]
    signature = headers["signature"]
    ss58_address = headers["ss58_address"]
    keypair = bt.Keypair(ss58_address=ss58_address)
    result = keypair.verify(message, signature)
    logger.info(f"Verification result: {result}")
    return result


def test_verify_headers():
    headers = get_headers()
    result = verify_headers(headers)
    assert result
