from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True, slots=True)
class StoreAffiliateConfig:
    affiliate_id: str = ""
    associate_tag: str = ""
    mapping: str = ""
    template: str = ""
    api_url: str = ""
    api_token: str = ""


@dataclass(frozen=True, slots=True)
class AffiliateConfig:
    mercado_livre: StoreAffiliateConfig
    amazon: StoreAffiliateConfig
    shopee: StoreAffiliateConfig
    cache_path: Path
    cache_ttl_hours: int = 720
    env_path: Path = DEFAULT_ENV_PATH
    env_file_found: bool = False

    @classmethod
    def from_environment(cls):
        env_path = DEFAULT_ENV_PATH.resolve()
        load_dotenv(dotenv_path=env_path, override=False)

        def store(prefix):
            return StoreAffiliateConfig(
                affiliate_id=os.getenv(
                    f"{prefix}_AFFILIATE_ID", ""
                ).strip(),
                associate_tag=os.getenv(
                    f"{prefix}_ASSOCIATE_TAG", ""
                ).strip(),
                mapping=os.getenv(
                    f"{prefix}_AFFILIATE_MAP", ""
                ).strip(),
                template=os.getenv(
                    f"{prefix}_AFFILIATE_TEMPLATE", ""
                ).strip(),
                api_url=os.getenv(
                    f"{prefix}_AFFILIATE_API_URL", ""
                ).strip(),
                api_token=os.getenv(
                    f"{prefix}_AFFILIATE_API_TOKEN", ""
                ).strip(),
            )

        try:
            ttl = max(int(os.getenv(
                "AFFILIATE_CACHE_TTL_HOURS", "720"
            )), 1)
        except ValueError:
            ttl = 720
        return cls(
            mercado_livre=store("MERCADOLIVRE"),
            amazon=store("AMAZON"),
            shopee=store("SHOPEE"),
            cache_path=Path(os.getenv(
                "AFFILIATE_CACHE_PATH",
                "data/affiliate_links_cache.db",
            )),
            cache_ttl_hours=ttl,
            env_path=env_path,
            env_file_found=env_path.is_file(),
        )
