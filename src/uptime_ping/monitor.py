"""One monitoring run: check every target, alert on changes, remember the result."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .checks import OK, CheckResult, Fetch, check_target
from .config import Target
from .notify import Alert
from .state import StateStore


@dataclass
class RunSummary:
    results: list[CheckResult] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    # Alerts that could not be delivered, as "name: error" strings.
    notify_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked": len(self.results),
            "unhealthy": sum(1 for r in self.results if r.status != OK),
            "results": [r.to_dict() for r in self.results],
            "alerts": [a.to_dict() for a in self.alerts],
            "notify_errors": self.notify_errors,
        }


def run_checks(targets: list[Target], fetch: Fetch, now: float, max_workers: int = 8) -> list[CheckResult]:
    """Check all targets concurrently; results come back in config order."""
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(targets))) as pool:
        return list(pool.map(lambda target: check_target(target, fetch, now), targets))


def alert_for(previous: str | None, result: CheckResult) -> Alert | None:
    """Decide whether this result is news.

    - Same status as last run: nothing.
    - First time a target is seen: alert only if it is unhealthy.
    - Any other change, including back to ok: alert.
    """
    if previous == result.status:
        return None
    if previous is None and result.status == OK:
        return None
    return Alert(result, previous)


def run_once(targets: list[Target], store: StateStore, fetch: Fetch, notifier, now: float) -> RunSummary:
    summary = RunSummary(results=run_checks(targets, fetch, now))
    for result in summary.results:
        previous = store.get(result.name)
        if previous == result.status:
            continue
        alert = alert_for(previous, result)
        if alert is not None:
            try:
                notifier.send(alert)
            except Exception as exc:
                # Leave the stored status alone so the next run sends this alert again.
                summary.notify_errors.append(f"{result.name}: {exc}")
                continue
            summary.alerts.append(alert)
        store.put(result.name, result.status, now)
    return summary
