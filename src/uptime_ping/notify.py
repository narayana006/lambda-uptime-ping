"""Turn status changes into messages and deliver them."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .checks import CERT_EXPIRING, DOWN, OK, SLOW, CheckResult

LABELS = {DOWN: "DOWN", SLOW: "SLOW", CERT_EXPIRING: "CERT", OK: "RECOVERED"}


@dataclass(frozen=True)
class Alert:
    result: CheckResult
    previous: str | None  # status before this run; None if the target was never seen

    @property
    def message(self) -> str:
        r = self.result
        text = f"[{LABELS[r.status]}] {r.name} ({r.url}): {r.detail}"
        if self.previous is not None:
            text += f" (was {self.previous})"
        return text

    def to_dict(self) -> dict:
        return {
            "name": self.result.name,
            "status": self.result.status,
            "previous": self.previous,
            "message": self.message,
        }


# post(url, payload, timeout_seconds) -> None, raises if delivery failed.
Post = Callable[[str, dict, float], None]


def post_json(url: str, payload: dict, timeout: float = 10.0) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # urlopen raises HTTPError for 4xx/5xx, which is what we want.
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


class SlackNotifier:
    """Posts each alert to a Slack incoming webhook as a plain text message."""

    def __init__(self, webhook_url: str, post: Post = post_json) -> None:
        if not webhook_url.startswith("https://"):
            raise ValueError("Slack webhook URL must start with https://")
        self.webhook_url = webhook_url
        self.post = post

    def send(self, alert: Alert) -> None:
        self.post(self.webhook_url, {"text": alert.message}, 10.0)


class PrintNotifier:
    """Writes alerts to stdout. In Lambda that means the function's log group."""

    def __init__(self, prefix: str = "ALERT ") -> None:
        self.prefix = prefix

    def send(self, alert: Alert) -> None:
        print(self.prefix + alert.message)
