from conftest import NOW, FakeFetch, ok
from uptime_ping.config import Target
from uptime_ping.monitor import run_checks, run_once
from uptime_ping.notify import SlackNotifier
from uptime_ping.state import MemoryStore

A = Target(name="a", url="https://a.example/", slow_ms=1000)
B = Target(name="b", url="https://b.example/", slow_ms=1000)


class Recorder:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send(self, alert):
        if self.fail:
            raise OSError("slack unreachable")
        self.messages.append(alert.message)


def run(fetch, store, notifier, targets=(A, B)):
    return run_once(list(targets), store, fetch, notifier, NOW)


def test_first_run_alerts_only_for_unhealthy_targets():
    fetch = FakeFetch(**{A.url: ok(), B.url: ok(code=503)})
    store, notifier = MemoryStore(), Recorder()
    summary = run(fetch, store, notifier)
    assert notifier.messages == ["[DOWN] b (https://b.example/): HTTP 503, expected 2xx or 3xx"]
    assert [a.result.name for a in summary.alerts] == ["b"]
    assert (store.get("a"), store.get("b")) == ("ok", "down")


def test_alerts_once_then_again_on_recovery():
    fetch = FakeFetch(**{A.url: ok(code=500)})
    store, notifier = MemoryStore(), Recorder()

    run(fetch, store, notifier, [A])
    run(fetch, store, notifier, [A])
    run(fetch, store, notifier, [A])
    assert len(notifier.messages) == 1  # still down: no repeat

    fetch.set(A.url, ok(ms=90))
    run(fetch, store, notifier, [A])
    assert notifier.messages[1] == "[RECOVERED] a (https://a.example/): HTTP 200 in 90 ms (was down)"

    run(fetch, store, notifier, [A])
    assert len(notifier.messages) == 2  # still ok: no repeat


def test_change_between_two_problems_alerts():
    fetch = FakeFetch(**{A.url: ok(code=500)})
    store, notifier = MemoryStore(), Recorder()
    run(fetch, store, notifier, [A])
    fetch.set(A.url, ok(ms=4000))
    run(fetch, store, notifier, [A])
    assert notifier.messages[1].startswith("[SLOW] a ")
    assert notifier.messages[1].endswith("(was down)")


def test_cert_warning_is_sent_once_while_days_tick_down():
    store, notifier = MemoryStore(), Recorder()
    for days in (5, 4, 3):
        run(FakeFetch(**{A.url: ok(cert_days=days)}), store, notifier, [A])
    assert len(notifier.messages) == 1
    assert notifier.messages[0].startswith("[CERT] a (https://a.example/): TLS certificate expires in 5.0 days")


def test_failed_notification_is_retried_next_run():
    fetch = FakeFetch(**{A.url: ok(code=500)})
    store, notifier = MemoryStore(), Recorder()
    notifier.fail = True
    summary = run(fetch, store, notifier, [A])
    assert summary.alerts == []
    assert summary.notify_errors == ["a: slack unreachable"]
    assert store.get("a") is None  # not recorded, so it is still "news"

    notifier.fail = False
    summary = run(fetch, store, notifier, [A])
    assert len(notifier.messages) == 1 and summary.notify_errors == []
    assert store.get("a") == "down"


def test_results_keep_config_order_and_every_target_is_fetched():
    targets = [Target(name=f"t{i}", url=f"https://t{i}.example/") for i in range(20)]
    fetch = FakeFetch(**{t.url: ok(ms=i) for i, t in enumerate(targets)})
    results = run_checks(targets, fetch, NOW)
    assert [r.name for r in results] == [t.name for t in targets]
    assert sorted(url for url, _ in fetch.calls) == sorted(t.url for t in targets)
    assert run_checks([], fetch, NOW) == []


def test_summary_dict():
    fetch = FakeFetch(**{A.url: ok(), B.url: TimeoutError()})
    data = run(fetch, MemoryStore(), Recorder()).to_dict()
    assert (data["checked"], data["unhealthy"]) == (2, 1)
    assert data["alerts"] == [
        {
            "name": "b",
            "status": "down",
            "previous": None,
            "message": "[DOWN] b (https://b.example/): timed out after 10 s",
        }
    ]


def test_slack_notifier_posts_text_payload():
    posts = []
    notifier = SlackNotifier("https://hooks.slack.example/x", lambda *args: posts.append(args))
    run(FakeFetch(**{A.url: ok(code=500)}), MemoryStore(), notifier, [A])
    assert posts == [
        (
            "https://hooks.slack.example/x",
            {"text": "[DOWN] a (https://a.example/): HTTP 500, expected 2xx or 3xx"},
            10.0,
        )
    ]


def test_slack_webhook_must_be_https():
    import pytest

    with pytest.raises(ValueError):
        SlackNotifier("http://hooks.slack.example/x")
