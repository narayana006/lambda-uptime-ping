"""Load and validate the list of URLs to check."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = {"timeout_seconds": 10.0, "slow_ms": 2000.0, "cert_warn_days": 14.0}


class ConfigError(ValueError):
    """The config file is missing something or has a bad value."""


@dataclass(frozen=True)
class Target:
    name: str
    url: str
    timeout_seconds: float = DEFAULTS["timeout_seconds"]
    slow_ms: float = DEFAULTS["slow_ms"]
    cert_warn_days: float = DEFAULTS["cert_warn_days"]
    # None means "any 2xx or 3xx status is healthy".
    expect_status: tuple[int, ...] | None = None


def _positive_number(value, field: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{where}: {field} must be a positive number, got {value!r}")
    return float(value)


def _expect_status(value, where: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    codes = value if isinstance(value, list) else [value]
    for code in codes:
        if isinstance(code, bool) or not isinstance(code, int) or not 100 <= code <= 599:
            raise ConfigError(f"{where}: expect_status must be HTTP status codes, got {value!r}")
    if not codes:
        raise ConfigError(f"{where}: expect_status must not be an empty list")
    return tuple(codes)


def parse_config(data) -> list[Target]:
    """Turn the decoded JSON document into validated targets."""
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object with a 'targets' list")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("'defaults' must be an object")
    unknown = set(defaults) - set(DEFAULTS) - {"expect_status"}
    if unknown:
        raise ConfigError(f"defaults: unknown setting(s) {sorted(unknown)}")
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ConfigError("'targets' must be a non-empty list")

    targets: list[Target] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_targets):
        where = f"targets[{index}]"
        if isinstance(raw, str):
            raw = {"url": raw}
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: must be a URL string or an object")
        unknown = set(raw) - set(DEFAULTS) - {"name", "url", "expect_status"}
        if unknown:
            raise ConfigError(f"{where}: unknown setting(s) {sorted(unknown)}")
        url = raw.get("url")
        if not isinstance(url, str) or not url:
            raise ConfigError(f"{where}: 'url' is required")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConfigError(f"{where}: url must be an http:// or https:// URL, got {url!r}")
        name = raw.get("name", url)
        if not isinstance(name, str) or not name:
            raise ConfigError(f"{where}: 'name' must be a non-empty string")
        if name in seen:
            raise ConfigError(f"{where}: duplicate target name {name!r}")
        seen.add(name)

        merged = {**DEFAULTS, **defaults, **raw}
        targets.append(
            Target(
                name=name,
                url=url,
                timeout_seconds=_positive_number(merged["timeout_seconds"], "timeout_seconds", where),
                slow_ms=_positive_number(merged["slow_ms"], "slow_ms", where),
                cert_warn_days=_positive_number(merged["cert_warn_days"], "cert_warn_days", where),
                expect_status=_expect_status(merged.get("expect_status"), where),
            )
        )
    return targets


def load_config(path: str | Path) -> list[Target]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    return parse_config(data)
