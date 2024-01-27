import json

from uptime_ping.state import DynamoStore, FileStore


def test_file_store_persists(tmp_path):
    path = tmp_path / "state.json"
    store = FileStore(path)
    assert store.get("a") is None
    store.put("a", "down", 1700000000.9)
    assert json.loads(path.read_text()) == {"a": {"status": "down", "since": 1700000000}}
    assert FileStore(path).get("a") == "down"


def test_dynamo_store_roundtrip(table):
    store = DynamoStore(table)
    assert store.get("a") is None
    store.put("a", "down", 1700000000.9)
    store.put("b", "ok", 1700000000)
    store.put("a", "ok", 1700000300)
    assert store.get("a") == "ok"
    assert table.get_item(Key={"target": "a"})["Item"] == {"target": "a", "status": "ok", "since": 1700000300}
    assert table.scan()["Count"] == 2
