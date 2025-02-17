from pydantic_settings import BaseSettings
from pydantic import BaseModel
from typing import Optional


class RedisConfig(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    username: Optional[str] = None
    password: Optional[str] = None


class MongoConfig(BaseModel):
    host: str = "localhost"
    port: int = 27017
    username: Optional[str] = None
    password: Optional[str] = None
    uri: Optional[str] = None

    database: str = "condenses"
    collection: str = "miner_stats"

    def get_uri(self) -> str:
        if self.uri:
            return self.uri
        if self.username and self.password:
            return f"mongodb://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"mongodb://{self.host}:{self.port}"


class ServerConfig(BaseModel):
    port: int = 9101
    host: str = "0.0.0.0"


class RestfulBittensorConfig(BaseModel):
    base_url: str = "http://localhost:9100"


class OrchestratorConfig(BaseModel):
    base_url: str = "http://localhost:9101"


class ScoringConfig(BaseModel):
    base_url: str = "http://localhost:9102"


class SynthesizingConfig(BaseModel):
    base_url: str = "http://localhost:9103"


class ValidatingConfig(BaseModel):
    batch_size: int = 10
    concurrent_forward: int = 2
    forward_sleep: float = 4
    max_compress_rate: float = 0.8
    synthetic_rate_limit: float = 0.5


class WalletConfig(BaseModel):
    path: str = "~/.bittensor/wallets"
    name: str = "default"
    hotkey: str = "default"


class Settings(BaseSettings):
    redis: RedisConfig = RedisConfig()
    mongo: MongoConfig = MongoConfig()
    server: ServerConfig = ServerConfig()
    validating: ValidatingConfig = ValidatingConfig()
    wallet: WalletConfig = WalletConfig()
    scoring: ScoringConfig = ScoringConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()
    restful: RestfulBittensorConfig = RestfulBittensorConfig()
    synthesizing: SynthesizingConfig = SynthesizingConfig()

    class Config:
        env_nested_delimiter = "__"


CONFIG = Settings()
