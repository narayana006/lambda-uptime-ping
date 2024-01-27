import json

import pytest

from conftest import NOW, FakeFetch, ok
from uptime_ping.cli import main

A, B = "https://a.example/", "https://b.example/"


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"targets": [{"name": "a", "url": A}, {"name": "b", "url": B}]}))
    return str(path)


def test_all_healthy_exits_zero(config, capsys):
    code = main(["--once", "--config", config], fetch=FakeFetch(**{A: ok(), B: ok(ms=30)}), now=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[0].split() == ["STATUS", "NAME", "HTTP", "TIME", "DETAIL"]
    assert "No status changes, nothing to alert on." in out


def test_unhealthy_exits_one_and_lists_alerts(config, capsys):
    fetch = FakeFetch(**{A: ok(), B: ConnectionRefusedError("Connection refused")})
    code = main(["--once", "--config", config], fetch=fetch, now=NOW)
    out = capsys.readouterr().out
    assert code == 1
    assert "Alerts (not sent, --notify is off):" in out
    assert "  [DOWN] b (https://b.example/): Connection refused" in out


def test_state_file_suppresses_repeat_alerts(config, tmp_path, capsys):
    state = str(tmp_path / "state.json")
    fetch = FakeFetch(**{A: ok(), B: ok(code=500)})
    args = ["--once", "--config", config, "--state-file", state, "--json"]

    assert main(args, fetch=fetch, now=NOW) == 1
    assert len(json.loads(capsys.readouterr().out)["alerts"]) == 1
    assert main(args, fetch=fetch, now=NOW) == 1  # still down, exit code says so
    assert json.loads(capsys.readouterr().out)["alerts"] == []

    fetch.set(B, ok())
    assert main(args, fetch=fetch, now=NOW) == 0
    (alert,) = json.loads(capsys.readouterr().out)["alerts"]
    assert alert["status"] == "ok" and alert["previous"] == "down"


def test_notify_posts_to_webhook_from_env(config, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    posts = []
    fetch = FakeFetch(**{A: ok(code=500), B: ok()})
    main(["--once", "--config", config, "--notify"], fetch=fetch, post=lambda *a: posts.append(a), now=NOW)
    assert [p[1]["text"] for p in posts] == ["[DOWN] a (https://a.example/): HTTP 500, expected 2xx or 3xx"]
    assert "Alerts sent to Slack:" in capsys.readouterr().out


def test_no_post_without_notify_flag(config, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/x")
    posts = []
    fetch = FakeFetch(**{A: ok(code=500), B: ok()})
    main(["--once", "--config", config], fetch=fetch, post=lambda *a: posts.append(a), now=NOW)
    assert posts == []


def test_usage_errors(config, tmp_path, capsys):
    assert main(["--config", config]) == 2
    assert "pass --once" in capsys.readouterr().err
    assert main(["--once", "--config", str(tmp_path / "nope.json")]) == 2
    assert "cannot read config file" in capsys.readouterr().err
    assert main(["--once", "--config", config, "--notify"]) == 2
    assert "SLACK_WEBHOOK_URL" in capsys.readouterr().err
