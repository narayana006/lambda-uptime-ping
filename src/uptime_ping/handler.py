"""AWS Lambda entry point, invoked on a schedule by EventBridge.

Environment variables:
  STATE_TABLE        DynamoDB table name (partition key `target`, string). Required.
  SLACK_WEBHOOK_URL  Slack incoming webhook. If empty, alerts only go to the log.
  CONFIG_PATH        Path of the config file. Default: config.json next to the code.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .checks import http_fetch
from .config import load_config
from .monitor import run_once
from .notify import PrintNotifier, SlackNotifier, post_json
from .state import DynamoStore


def _config_path() -> Path:
    explicit = os.environ.get("CONFIG_PATH")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("LAMBDA_TASK_ROOT", ".")) / "config.json"


def handle(event, context, *, fetch=http_fetch, post=post_json, table=None, now=None) -> dict:
    """Do one run. The keyword arguments exist so tests can replace every outside call."""
    targets = load_config(_config_path())
    if table is None:
        import boto3  # provided by the Lambda Python runtime

        table = boto3.resource("dynamodb").Table(os.environ["STATE_TABLE"])
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    notifier = SlackNotifier(webhook, post) if webhook else PrintNotifier()

    summary = run_once(targets, DynamoStore(table), fetch, notifier, time.time() if now is None else now)
    report = summary.to_dict()
    print(json.dumps(report))
    if summary.notify_errors:
        # Fail the invocation so the problem shows up in the function's Errors metric.
        raise RuntimeError("could not deliver alert(s): " + "; ".join(summary.notify_errors))
    return report


def lambda_handler(event, context):
    return handle(event, context)
