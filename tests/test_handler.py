import json
from pathlib import Path

import pytest

from conftest import NOW, FakeFetch, ok
from uptime_ping import handler

EVENT = json.loads((Path(__file__).parent.parent / "examples" / "scheduled-event.json").read_text())
WEB, API = "https://www.example.test/", "https://api.example.test/health"


@pytest.fixture
def env(monkeypatch, tmp_path, table):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"targets": [{"name": "web", "url": WEB}, {"name": "api", "url": API}]})
    )
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("STATE_TABLE", "state")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/services/T000/B000/XXXX")
    return table


def stored(table):
    return {item["target"]: item["status"] for item in table.scan()["Items"]}


def test_handler_alerts_on_change_and_stores_state(env):
    fetch = FakeFetch(**{WEB: ok(), API: ok(code=502)})
    posts = []

    def post(url, payload, timeout):
        posts.append((url, payload["text"]))

    def invoke():
        return handler.handle(EVENT, None, fetch=fetch, post=post, now=NOW)

    report = invoke()
    assert (report["checked"], report["unhealthy"]) == (2, 1)
    assert posts == [
        (
            "https://hooks.slack.example/services/T000/B000/XXXX",
            "[DOWN] api (https://api.example.test/health): HTTP 502, expected 2xx or 3xx",
        )
    ]
    assert stored(env) == {"web": "ok", "api": "down"}

    assert invoke()["alerts"] == []  # unchanged
    assert len(posts) == 1

    fetch.set(API, ok(ms=45))
    report = invoke()
    assert posts[1][1] == "[RECOVERED] api (https://api.example.test/health): HTTP 200 in 45 ms (was down)"
    assert stored(env) == {"web": "ok", "api": "ok"}
    json.dumps(report)  # the return value must be JSON-serialisable for Lambda


def test_handler_uses_default_boto3_table_from_env(env):
    # No table passed in: the handler builds one from STATE_TABLE (moto is active via the fixture).
    fetch = FakeFetch(**{WEB: ok(code=500), API: ok()})
    handler.handle(EVENT, None, fetch=fetch, post=lambda *a: None, now=NOW)
    assert stored(env) == {"web": "down", "api": "ok"}


def test_without_webhook_alerts_go_to_the_log(env, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")

    def post(*args):
        raise AssertionError("must not post without a webhook")

    fetch = FakeFetch(**{WEB: ok(), API: TimeoutError()})
    handler.handle(EVENT, None, fetch=fetch, post=post, now=NOW)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "ALERT [DOWN] api (https://api.example.test/health): timed out after 10 s"
    assert json.loads(out[1])["unhealthy"] == 1


def test_slack_failure_fails_the_invocation_and_keeps_alert_pending(env):
    fetch = FakeFetch(**{WEB: ok(), API: ok(code=500)})

    def broken_post(url, payload, timeout):
        raise OSError("HTTP Error 500")

    with pytest.raises(RuntimeError, match="could not deliver alert"):
        handler.handle(EVENT, None, fetch=fetch, post=broken_post, now=NOW)
    assert stored(env) == {"web": "ok"}

    posts = []
    handler.handle(EVENT, None, fetch=fetch, post=lambda u, p, t: posts.append(p), now=NOW)
    assert len(posts) == 1


def test_config_path_defaults_to_task_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))
    assert handler._config_path() == tmp_path / "config.json"


def test_bundled_config_is_valid():
    from uptime_ping.config import load_config

    root = Path(__file__).parent.parent
    for path in ("src/config.json", "examples/config.json", "examples/config.local.json"):
        assert load_config(root / path)
