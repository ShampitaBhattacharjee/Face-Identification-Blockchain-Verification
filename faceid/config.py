"""Environment-backed settings (loaded from .env via python-dotenv)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """All runtime secrets and switches. Never log `private_key` or API keys."""

    serpapi_key: str | None
    bing_key: str | None
    private_key: str | None
    rpc_url: str | None
    chain: str
    contract_address: str | None
    image_host: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        def clean(name: str) -> str | None:
            value = os.getenv(name, "").strip()
            return value or None

        return cls(
            serpapi_key=clean("SERPAPI_KEY"),
            bing_key=clean("BING_API_KEY"),
            private_key=clean("PRIVATE_KEY"),
            rpc_url=clean("RPC_URL"),
            chain=(clean("CHAIN") or "amoy").lower(),
            contract_address=clean("CONTRACT_ADDRESS"),
            image_host=clean("IMAGE_HOST"),
        )
