from pydantic_settings import BaseSettings
from pydantic import BaseModel
from typing import Optional


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    username: Optional[str] = None
    password: Optional[str] = None


class ServerConfig(BaseModel):
    port: int = 9101
    host: str = "0.0.0.0"


class SidecarBittensorConfig(BaseModel):
    base_url: str = "http://localhost:9103"


class OrchestratorConfig(BaseModel):
    base_url: str = "http://localhost:9101"


class ScoringConfig(BaseModel):
    base_url: str = "http://localhost:9102"


class SynthesizingConfig(BaseModel):
    base_url: str = "http://localhost:9100"


class ScoringRateConfig(BaseModel):
    interval: int = 600
    max_scoring_count: int = 4
    redis_key: str = "scored_uid"


class ValidatingConfig(BaseModel):
    batch_size: int = 4
    concurrent_forward: int = 128
    forward_sleep: float = 4
    max_compress_rate: float = 0.8
    synthetic_rate_limit: float = 0.5
    max_log_columns: int = 4
    log_ttl: int = 300
    panel_width: int = 40
    scoring_rate: ScoringRateConfig = ScoringRateConfig()


class OwnerServerConfig(BaseModel):
    base_url: str = "https://subnet-reporting.condenses.ai"


class Settings(BaseSettings):
    redis: RedisConfig = RedisConfig()
    server: ServerConfig = ServerConfig()
    validating: ValidatingConfig = ValidatingConfig()
    scoring: ScoringConfig = ScoringConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()
    sidecar_bittensor: SidecarBittensorConfig = SidecarBittensorConfig()
    synthesizing: SynthesizingConfig = SynthesizingConfig()
    owner_server: OwnerServerConfig = OwnerServerConfig()
    wallet_name: str = "default"
    wallet_hotkey: str = "default"
    wallet_path: str = "~/.bittensor/wallets"
    version: int = 100

    class Config:
        env_nested_delimiter = "__"
        env_file = ".env"
        extra = "ignore"


CONFIG = Settings()

from rich.console import Console
from rich.panel import Panel

console = Console()
settings_dict = CONFIG.model_dump()

for section, values in settings_dict.items():
    console.print(
        Panel.fit(
            str(values),
            title=f"[bold blue]{section}[/bold blue]",
            border_style="green",
        )
    )
