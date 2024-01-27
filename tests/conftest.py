import os

# Set before boto3 is imported anywhere, so no test can reach a real AWS account.
_FAKE_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/credentials",
    "AWS_CONFIG_FILE": "/nonexistent/config",
}
os.environ.update(_FAKE_ENV)
os.environ.pop("AWS_PROFILE", None)

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402

from uptime_ping.checks import FetchResponse  # noqa: E402

NOW = 1_750_000_000.0
DAY = 86400


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for key in ("SLACK_WEBHOOK_URL", "STATE_TABLE", "CONFIG_PATH", "LAMBDA_TASK_ROOT"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def table():
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="state",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "target", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "target", "KeyType": "HASH"}],
        )
        yield boto3.resource("dynamodb").Table("state")


class FakeFetch:
    """A fetch function whose answer per URL can be changed between runs."""

    def __init__(self, **responses):
        self.responses = dict(responses)
        self.calls = []

    def set(self, url, response):
        self.responses[url] = response

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def ok(ms=120.0, code=200, cert_days=None):
    expires = None if cert_days is None else NOW + cert_days * DAY
    return FetchResponse(code, ms, expires)


@pytest.fixture
def fake_fetch():
    return FakeFetch()
