"""Where the last known status of each target is kept between runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class StateStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def put(self, name: str, status: str, now: float) -> None: ...


class MemoryStore:
    """Forgets everything when the process exits."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}

    def get(self, name: str) -> str | None:
        item = self.items.get(name)
        return item["status"] if item else None

    def put(self, name: str, status: str, now: float) -> None:
        self.items[name] = {"status": status, "since": int(now)}


class FileStore(MemoryStore):
    """A JSON file, for the local CLI."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8"))

    def put(self, name: str, status: str, now: float) -> None:
        super().put(name, status, now)
        self.path.write_text(json.dumps(self.items, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class DynamoStore:
    """One item per target in a DynamoDB table whose partition key is `target` (string).

    Takes a boto3 Table resource so tests can hand in a moto-backed one.
    Uses only GetItem and PutItem.
    """

    def __init__(self, table) -> None:
        self.table = table

    def get(self, name: str) -> str | None:
        item = self.table.get_item(Key={"target": name}, ConsistentRead=True).get("Item")
        return item["status"] if item else None

    def put(self, name: str, status: str, now: float) -> None:
        self.table.put_item(Item={"target": name, "status": status, "since": int(now)})
