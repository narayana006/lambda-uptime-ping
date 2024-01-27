"""Local command line: run the same checks once, without AWS."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .checks import OK, http_fetch
from .config import ConfigError, load_config
from .monitor import run_once
from .notify import SlackNotifier
from .state import FileStore, MemoryStore


class _Collect:
    """Keeps alerts for the report instead of sending them anywhere."""

    def send(self, alert) -> None:
        pass


def _table(results) -> str:
    rows = [("STATUS", "NAME", "HTTP", "TIME", "DETAIL")]
    for r in results:
        rows.append(
            (
                r.status,
                r.name,
                "-" if r.status_code is None else str(r.status_code),
                "-" if r.elapsed_ms is None else f"{r.elapsed_ms:.0f} ms",
                r.detail,
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])) + "  " + row[4] for row in rows
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uptime-ping",
        description="Check the URLs in a config file once and print the result. "
        "The scheduled version of this is the Lambda function in template.yaml.",
    )
    parser.add_argument("--once", action="store_true", help="run all checks one time and exit (required)")
    parser.add_argument("--config", required=True, metavar="FILE", help="JSON config file listing the targets")
    parser.add_argument(
        "--state-file",
        metavar="FILE",
        help="remember each target's status in this JSON file, so repeated runs "
        "only report changes (the Lambda uses DynamoDB for this)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="also post alerts to the Slack webhook in $SLACK_WEBHOOK_URL (off by default)",
    )
    parser.add_argument("--json", action="store_true", help="print the run summary as JSON")
    return parser


def main(argv=None, *, fetch=http_fetch, post=None, now=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.once:
        print("uptime-ping: only --once mode exists locally; pass --once", file=sys.stderr)
        return 2
    try:
        targets = load_config(args.config)
    except ConfigError as exc:
        print(f"uptime-ping: {exc}", file=sys.stderr)
        return 2

    notifier = _Collect()
    if args.notify:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook:
            print("uptime-ping: --notify needs SLACK_WEBHOOK_URL to be set", file=sys.stderr)
            return 2
        try:
            notifier = SlackNotifier(webhook, post) if post else SlackNotifier(webhook)
        except ValueError as exc:
            print(f"uptime-ping: {exc}", file=sys.stderr)
            return 2

    store = FileStore(args.state_file) if args.state_file else MemoryStore()
    summary = run_once(targets, store, fetch, notifier, time.time() if now is None else now)

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(_table(summary.results))
        print()
        if summary.alerts:
            print("Alerts sent to Slack:" if args.notify else "Alerts (not sent, --notify is off):")
            for alert in summary.alerts:
                print("  " + alert.message)
        else:
            print("No status changes, nothing to alert on.")
        for error in summary.notify_errors:
            print(f"uptime-ping: could not deliver alert for {error}", file=sys.stderr)

    if summary.notify_errors:
        return 3
    return 0 if all(r.status == OK for r in summary.results) else 1


if __name__ == "__main__":
    sys.exit(main())
