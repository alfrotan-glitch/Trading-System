"""Secrets provider abstraction with redaction."""

from __future__ import annotations

import os
from typing import Protocol


class SecretsProvider(Protocol):
    def get(self, key: str) -> str: ...


class EnvSecretsProvider:
    """Reads secrets from env vars. Scopes by env prefix.

    Example: key 'mt5/password' with env 'paper' looks for QTS_PAPER_MT5_PASSWORD.
    Live secrets are isolated: paper provider cannot read live/*.
    """

    def __init__(self, env: str = "dev"):
        self.env = env

    def get(self, key: str) -> str:
        # key like "mt5/password" or "mt5_password"
        norm = key.replace("/", "_").replace("-", "_").upper()
        env_prefix = f"QTS_{self.env.upper()}_"
        full = env_prefix + norm
        val = os.getenv(full) or os.getenv(f"QTS_{norm}")
        if val is None:
            raise KeyError(f"secret not found: {key} (looked for {full})")
        return val

    def redact(self, text: str) -> str:
        # naive redaction for logs
        for secret_key in ["PASSWORD", "TOKEN", "SECRET", "API_KEY"]:
            val = os.getenv(f"QTS_{secret_key}") or os.getenv(f"QTS_{self.env.upper()}_{secret_key}")
            if val and val in text:
                text = text.replace(val, "***REDACTED***")
        return text
