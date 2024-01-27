"""Static checks on the SAM template. It is never deployed by the tests."""

import importlib
import inspect
from pathlib import Path

import yaml

from uptime_ping import state

ROOT = Path(__file__).parent.parent


class _Loader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {tag_suffix: value}


_Loader.add_multi_constructor("!", _intrinsic)

TEMPLATE = yaml.load((ROOT / "template.yaml").read_text(), Loader=_Loader)
FUNCTION = TEMPLATE["Resources"]["PingFunction"]["Properties"]


def test_handler_path_points_at_real_code():
    module_name, function_name = FUNCTION["Handler"].rsplit(".", 1)
    assert (ROOT / FUNCTION["CodeUri"] / module_name.replace(".", "/")).with_suffix(".py").exists()
    module = importlib.import_module(module_name)
    assert list(inspect.signature(getattr(module, function_name)).parameters) == ["event", "context"]
    assert (ROOT / FUNCTION["CodeUri"] / "config.json").exists()


def test_iam_policy_is_only_what_the_store_uses():
    (policy,) = FUNCTION["Policies"]
    (statement,) = policy["Statement"]
    assert statement["Resource"] == {"GetAtt": "StateTable.Arn"}
    assert sorted(statement["Action"]) == ["dynamodb:GetItem", "dynamodb:PutItem"]
    # The store really only calls those two operations.
    source = inspect.getsource(state.DynamoStore)
    assert "get_item" in source and "put_item" in source
    for other in ("scan", "query", "delete_item", "update_item", "batch"):
        assert other not in source


def test_table_key_and_environment_match_the_code():
    table = TEMPLATE["Resources"]["StateTable"]["Properties"]
    assert table["KeySchema"] == [{"AttributeName": "target", "KeyType": "HASH"}]
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    env = FUNCTION["Environment"]["Variables"]
    assert env["STATE_TABLE"] == {"Ref": "StateTable"}
    assert env["SLACK_WEBHOOK_URL"] == {"Ref": "SlackWebhookUrl"}
    assert TEMPLATE["Parameters"]["SlackWebhookUrl"]["NoEcho"] is True


def test_runs_on_a_schedule():
    event = FUNCTION["Events"]["Schedule"]
    assert event["Type"] == "Schedule"
    assert event["Properties"]["Schedule"] == {"Ref": "ScheduleExpression"}
    assert TEMPLATE["Parameters"]["ScheduleExpression"]["Default"] == "rate(5 minutes)"
