"""Run the real Lambda handler on this machine, with no AWS account.

    pip install -e ".[dev]"
    python examples/invoke_local.py

What is real: the handler, the HTTP checks (against examples/demo_server.py,
started in-process on 127.0.0.1:8808) and the DynamoDB calls.
What is fake: DynamoDB itself is moto's in-memory mock, and Slack is replaced
by a function that prints the payload it was asked to post.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

# Dummy credentials before boto3 is imported, so nothing can reach a real account.
os.environ.update(
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_SESSION_TOKEN="testing",
    AWS_DEFAULT_REGION="us-east-1",
    AWS_SHARED_CREDENTIALS_FILE="/nonexistent/credentials",
    AWS_CONFIG_FILE="/nonexistent/config",
)
os.environ.pop("AWS_PROFILE", None)

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from demo_server import DemoServer  # noqa: E402

from uptime_ping import handler  # noqa: E402


def invoke(title, event):
    print(f"\n== {title}")
    posted = []
    # The handler prints its full JSON report (in Lambda that goes to CloudWatch
    # Logs). Hide it here and print a shorter view of the returned value.
    with contextlib.redirect_stdout(io.StringIO()):
        report = handler.handle(event, None, post=lambda url, payload, timeout: posted.append(payload))
    for payload in posted:
        print(f"  slack <- {json.dumps(payload)}")
    statuses = ", ".join(f"{r['name']}={r['status']}" for r in report["results"])
    print(f"  checked {report['checked']}, unhealthy {report['unhealthy']}, alerts {len(report['alerts'])}")
    print(f"  {statuses}")


def main():
    event = json.loads((HERE / "scheduled-event.json").read_text())
    os.environ["CONFIG_PATH"] = str(HERE / "config.local.json")
    os.environ["STATE_TABLE"] = "uptime-ping-state"
    os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.example/services/T000/B000/XXXX"

    server = DemoServer(8808).start()
    try:
        with mock_aws():
            boto3.client("dynamodb").create_table(
                TableName="uptime-ping-state",
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[{"AttributeName": "target", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "target", "KeyType": "HASH"}],
            )
            invoke("run 1: first run, two targets are unhealthy", event)
            invoke("run 2: nothing changed, so no alerts", event)
            server.outage = True
            invoke("run 3: the whole site starts answering 503", event)
            server.outage = False
            invoke("run 4: the outage is over", event)

            print("\n== state table after run 4")
            items = boto3.resource("dynamodb").Table("uptime-ping-state").scan()["Items"]
            for item in sorted(items, key=lambda i: i["target"]):
                print(f"  {item['target']}: {item['status']}")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
