"""Budget caps and cost ledger for paid APIs.

Free OpenRouter models cost 0, but every call is recorded. If a non-free model
is configured, caps are enforced before the call and usage is appended to
logs/costs.jsonl.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import Lock

from .config import Config, ConfigError, get_config

_LOCK = Lock()
_RUN_COST = 0.0


class BudgetExceeded(ConfigError):
    pass


def _ledger_path(cfg: Config):
    return cfg.log_dir / "costs.jsonl"


def _records(cfg: Config) -> list[dict]:
    path = _ledger_path(cfg)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def totals(cfg: Config) -> dict[str, float]:
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    per_day = per_month = 0.0
    for row in _records(cfg):
        try:
            cost = float(row.get("cost_usd", 0))
            ts = str(row.get("ts", ""))
        except (TypeError, ValueError):
            continue
        per_month += cost
        if ts.startswith(day):
            per_day += cost
    with _LOCK:
        per_run = _RUN_COST
    return {"run": per_run, "day": per_day, "month": per_month}


def reset_run_total() -> None:
    """Reset the in-process run counter (used by tests and long-lived services)."""
    global _RUN_COST
    with _LOCK:
        _RUN_COST = 0.0


def check_budget(cfg: Config, estimated_cost: float, *, tool: str) -> None:
    current = totals(cfg)
    if estimated_cost + current["run"] > cfg.max_cost_per_run:
        raise BudgetExceeded(f"{tool}: per-run budget cap reached")
    if estimated_cost + current["day"] > cfg.max_cost_per_day:
        raise BudgetExceeded(f"{tool}: daily budget cap reached")
    if estimated_cost + current["month"] > cfg.max_cost_per_month:
        raise BudgetExceeded(f"{tool}: monthly budget cap reached")


def estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    if model.endswith(":free") or "/free" in model:
        return 0.0
    # Conservative fallback for unknown paid models: $1/M input, $3/M output.
    return (prompt_tokens / 1_000_000) * 1.0 + (completion_tokens / 1_000_000) * 3.0


def record_cost(
    cfg: Config,
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    tool: str,
) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cost_usd": round(float(cost_usd), 6),
        "tool": tool,
    }
    global _RUN_COST
    with _LOCK:
        with _ledger_path(cfg).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
        _RUN_COST += float(cost_usd)
