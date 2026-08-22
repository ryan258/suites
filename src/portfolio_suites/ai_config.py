"""Fail-closed OpenRouter configuration and role routing for suite AI work.

Note: This module defines strict configuration schemas, environment loading, and
role-based routing parameters ahead of active outbound model client consumers.
It does not execute HTTP requests itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .paths import SUITES_ROOT

DEFAULT_ENV_PATH = SUITES_ROOT / ".env"
DEFAULT_MODEL = "openrouter/auto"


class AIConfigError(ValueError):
    """Raised when OpenRouter configuration is missing or invalid."""


ROLE_PURPOSES = {
    "orchestrator": "Plan and route bounded work across suite owners and contracts.",
    "analyst": "Synthesize source-linked evidence without collapsing uncertainty.",
    "reviewer": "Adversarially inspect correctness, safety, provenance, and release claims.",
    "creative": "Draft creative artifacts while preserving governed inputs and approvals.",
    "accessibility": "Explain accessibility evidence while preserving manual-review boundaries.",
}

ROLE_DEFAULTS = {
    "orchestrator": {"temperature": 0.2, "max_tokens": 4096},
    "analyst": {"temperature": 0.1, "max_tokens": 6144},
    "reviewer": {"temperature": 0.0, "max_tokens": 4096},
    "creative": {"temperature": 0.7, "max_tokens": 6144},
    "accessibility": {"temperature": 0.0, "max_tokens": 4096},
}


@dataclass(frozen=True)
class AIRoleConfig:
    """Resolved model and generation budget for one semantic AI role."""

    name: str
    purpose: str
    model: str
    temperature: float
    max_tokens: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class OpenRouterConfig:
    """Resolved OpenRouter connection metadata and role assignments."""

    api_key: str = field(repr=False)
    base_url: str
    app_url: str
    app_title: str
    timeout_seconds: float
    roles: Mapping[str, AIRoleConfig]

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise AIConfigError(
                "OPENROUTER_API_KEY is not configured. Add it to the git-ignored .env file."
            )
        return self.api_key

    def role(self, name: str) -> AIRoleConfig:
        try:
            return self.roles[name]
        except KeyError as error:
            available = ", ".join(sorted(self.roles))
            raise AIConfigError(
                f"Unknown AI role '{name}'. Available roles: {available}."
            ) from error

    def request_headers(self) -> dict[str, str]:
        """Build OpenRouter headers without exposing the key in summaries or logs."""
        headers = {
            "Authorization": f"Bearer {self.require_api_key()}",
            "Content-Type": "application/json",
        }
        if self.app_url:
            headers["HTTP-Referer"] = self.app_url
        if self.app_title:
            headers["X-OpenRouter-Title"] = self.app_title
        return headers

    def safe_summary(self) -> dict[str, Any]:
        """Return diagnostics safe for terminals, tests, and evidence files."""
        return {
            "provider": "openrouter",
            "api_key_configured": self.api_key_configured,
            "base_url": self.base_url,
            "app_url": self.app_url,
            "app_title": self.app_title,
            "timeout_seconds": self.timeout_seconds,
            "roles": {name: role.as_dict() for name, role in self.roles.items()},
        }


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_file(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Read a small dotenv subset without executing shell syntax or expanding values."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise AIConfigError(f"Invalid dotenv entry at {path}:{line_number}.")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or not key[0].isalpha():
            raise AIConfigError(f"Invalid dotenv key at {path}:{line_number}.")
        values[key] = _unquote(value.strip())
    return values


def _float_value(values: Mapping[str, str], key: str, default: float) -> float:
    raw = values.get(key, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise AIConfigError(f"{key} must be a number.") from error
    return value


def _int_value(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise AIConfigError(f"{key} must be an integer.") from error
    return value


def load_openrouter_config(
    env_path: Path = DEFAULT_ENV_PATH,
    environ: Mapping[str, str] | None = None,
    require_api_key: bool = False,
) -> OpenRouterConfig:
    """Resolve .env plus process overrides into validated OpenRouter role config."""
    values = read_env_file(env_path)
    process_values = os.environ if environ is None else environ
    values.update(process_values)

    api_key = values.get("OPENROUTER_API_KEY", "").strip()
    base_url = values.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    app_url = values.get("OPENROUTER_APP_URL", "").strip()
    app_title = values.get("OPENROUTER_APP_TITLE", "Ryan Project Suites").strip()
    timeout_seconds = _float_value(values, "OPENROUTER_TIMEOUT_SECONDS", 60.0)
    default_model = values.get("OPENROUTER_DEFAULT_MODEL", DEFAULT_MODEL).strip()

    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise AIConfigError("OPENROUTER_BASE_URL must be an absolute HTTP(S) URL.")
    if app_url:
        parsed_app_url = urlparse(app_url)
        if parsed_app_url.scheme not in {"http", "https"} or not parsed_app_url.netloc:
            raise AIConfigError("OPENROUTER_APP_URL must be an absolute HTTP(S) URL when set.")
    if timeout_seconds <= 0:
        raise AIConfigError("OPENROUTER_TIMEOUT_SECONDS must be greater than zero.")
    if not default_model:
        raise AIConfigError("OPENROUTER_DEFAULT_MODEL must not be empty.")

    roles: dict[str, AIRoleConfig] = {}
    for role_name, purpose in ROLE_PURPOSES.items():
        prefix = f"OPENROUTER_ROLE_{role_name.upper()}"
        defaults = ROLE_DEFAULTS[role_name]
        model = values.get(f"{prefix}_MODEL", default_model).strip()
        temperature = _float_value(values, f"{prefix}_TEMPERATURE", defaults["temperature"])
        max_tokens = _int_value(values, f"{prefix}_MAX_TOKENS", defaults["max_tokens"])

        if not model:
            raise AIConfigError(f"{prefix}_MODEL must not be empty.")
        if not 0.0 <= temperature <= 2.0:
            raise AIConfigError(f"{prefix}_TEMPERATURE must be between 0.0 and 2.0.")
        if max_tokens <= 0:
            raise AIConfigError(f"{prefix}_MAX_TOKENS must be greater than zero.")

        roles[role_name] = AIRoleConfig(
            name=role_name,
            purpose=purpose,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    config = OpenRouterConfig(
        api_key=api_key,
        base_url=base_url,
        app_url=app_url,
        app_title=app_title,
        timeout_seconds=timeout_seconds,
        roles=roles,
    )
    if require_api_key:
        config.require_api_key()
    return config
