import json

import pytest

from uptime_ping.config import ConfigError, load_config, parse_config


def test_defaults_and_overrides():
    targets = parse_config(
        {
            "defaults": {"slow_ms": 800, "timeout_seconds": 5},
            "targets": [
                "https://a.example/",
                {"name": "b", "url": "http://b.example/health", "slow_ms": 100, "expect_status": [200, 204]},
            ],
        }
    )
    a, b = targets
    assert (a.name, a.url, a.slow_ms, a.timeout_seconds, a.cert_warn_days) == (
        "https://a.example/",
        "https://a.example/",
        800.0,
        5.0,
        14.0,
    )
    assert a.expect_status is None
    assert (b.name, b.slow_ms, b.expect_status) == ("b", 100.0, (200, 204))


def test_single_expect_status_becomes_tuple():
    (target,) = parse_config({"targets": [{"url": "https://a.example", "expect_status": 204}]})
    assert target.expect_status == (204,)


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "JSON object"),
        ({}, "non-empty list"),
        ({"targets": []}, "non-empty list"),
        ({"targets": [{}]}, "'url' is required"),
        ({"targets": ["ftp://a.example/file"]}, "http:// or https://"),
        ({"targets": ["file:///etc/passwd"]}, "http:// or https://"),
        ({"targets": ["https://"]}, "http:// or https://"),
        ({"targets": [{"url": "https://a.example", "slow_ms": 0}]}, "slow_ms must be a positive number"),
        ({"targets": [{"url": "https://a.example", "timeout_seconds": "5"}]}, "timeout_seconds"),
        ({"targets": [{"url": "https://a.example", "expect_status": [200, 99]}]}, "expect_status"),
        ({"targets": [{"url": "https://a.example", "expect_status": []}]}, "empty"),
        ({"targets": [{"url": "https://a.example", "slowms": 5}]}, "unknown setting"),
        ({"defaults": {"retries": 3}, "targets": ["https://a.example"]}, "unknown setting"),
        ({"targets": ["https://a.example", "https://a.example"]}, "duplicate target name"),
    ],
)
def test_invalid_config(data, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_load_config_file_errors(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(bad)
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"targets": ["https://a.example"]}))
    assert len(load_config(good)) == 1
