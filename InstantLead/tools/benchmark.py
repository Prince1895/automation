#!/usr/bin/env python3
"""Benchmark the end-to-end dry-run pipeline on synthetic labelled leads.

Purpose: measure processing time, tier/spam accuracy against known labels, and
cost per lead. Runs in an isolated temporary database and outbox; it never
touches the live database, Google, or paid APIs.
Inputs: --leads (default 100), --seed (default 42), --out JSON path.
Outputs: console JSON + benchmarks/latest.json.
Example: python3 tools/benchmark.py --leads 100
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.pipeline import ingest_and_process
from tools.lib.config import get_config, reset_config_cache
from tools.lib.db import connect, init_db
from tools.lib.demo import generate_demo_leads
from tools.lib.leads import get_lead
from tools.lib.replies import approve_first_reply, list_pending, reply_metrics


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _isolate(tmp: Path) -> None:
    os.environ.update(
        {
            "DRY_RUN": "1",
            "DB_PATH": str(tmp / "benchmark.db"),
            "ARCHIVE_DIR": str(tmp / "archive"),
            "OUTBOX_DIR": str(tmp / "outbox"),
            "LOG_DIR": str(tmp / "logs"),
            "BACKUP_DIR": str(tmp / "backups"),
            "LLM_ENABLED": "0",
            "WORKER_ENABLED": "0",
            "SCHEDULER_ENABLED": "0",
            "BACKUP_ENABLED": "0",
            "ALERT_CHECK_ENABLED": "0",
            "FIRST_REPLY_MODE": "approval",
            "SALES_EMAILS": "benchmark@example.invalid",
            "SHEET_ID": "",
            "DRIVE_FOLDER_ID": "",
        }
    )
    reset_config_cache()


def run_benchmark(count: int, seed: int) -> dict:
    records = generate_demo_leads(count, seed)
    timings: list[float] = []
    correct_tier = correct_spam = failures = 0
    confusion: dict[str, dict[str, int]] = {}
    sample_results = []

    with tempfile.TemporaryDirectory(prefix="instantlead-bench-") as raw_tmp:
        tmp = Path(raw_tmp)
        _isolate(tmp)
        cfg = get_config()
        cfg.ensure_dirs()
        init_db(cfg.db_path)
        conn = connect(cfg.db_path)
        try:
            started = time.perf_counter()
            for record in records:
                t0 = time.perf_counter()
                try:
                    result = ingest_and_process(
                        conn,
                        cfg,
                        source=record["source"],
                        payload=record["payload"],
                        external_id=f"DEMO-{record['demo_index']:04d}",
                    )
                    lead = get_lead(conn, result["leads"][0]) if result["leads"] else None
                except Exception as exc:  # pragma: no cover - defensive
                    failures += 1
                    lead = None
                    sample_results.append({"error": type(exc).__name__})
                timings.append(time.perf_counter() - t0)
                if not lead:
                    continue
                actual_tier = str(lead.get("tier") or "COLD")
                expected = record["expected_tier"]
                confusion.setdefault(expected, {}).setdefault(actual_tier, 0)
                confusion[expected][actual_tier] += 1
                correct_tier += int(actual_tier == expected)
                correct_spam += int(bool(lead.get("is_spam")) == bool(record["expected_spam"]))
                if len(sample_results) < 5:
                    sample_results.append(
                        {
                            "source": record["source"],
                            "expected": expected,
                            "actual": actual_tier,
                            "score": lead.get("score"),
                        }
                    )
            elapsed = time.perf_counter() - started
            for row in list_pending(conn, len(records)):
                approve_first_reply(conn, row["lead_id"], cfg, actor="benchmark")
            metrics = reply_metrics(conn, cfg)
        finally:
            conn.close()

        cost_total = 0.0
        ledger = cfg.log_dir / "costs.jsonl"
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                try:
                    cost_total += float(json.loads(line).get("cost_usd", 0))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

    processed = len(records) - failures
    mean_seconds = statistics.fmean(timings) if timings else 0.0
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "leads": count,
        "seed": seed,
        "processed": processed,
        "failures": failures,
        "processing": {
            "total_seconds": round(elapsed, 3),
            "mean_ms_per_lead": round(mean_seconds * 1000, 2),
            "p50_ms_per_lead": round(_percentile(timings, 0.50) * 1000, 2),
            "p95_ms_per_lead": round(_percentile(timings, 0.95) * 1000, 2),
            "max_ms_per_lead": round(max(timings, default=0.0) * 1000, 2),
            "throughput_per_second": round(processed / elapsed, 2) if elapsed else 0.0,
        },
        "accuracy": {
            "tier_correct": correct_tier,
            "tier_accuracy": round(correct_tier / processed, 4) if processed else 0.0,
            "spam_correct": correct_spam,
            "spam_accuracy": round(correct_spam / processed, 4) if processed else 0.0,
            "confusion": confusion,
        },
        "cost": {
            "total_usd": round(cost_total, 6),
            "per_lead_usd": round(cost_total / processed, 8) if processed else 0.0,
            "note": "Rules-only/free-model run; no paid API calls were made.",
        },
        "first_reply": metrics,
        "samples": sample_results,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the InstantLead dry-run pipeline")
    parser.add_argument("--leads", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/latest.json"))
    args = parser.parse_args()

    result = run_benchmark(args.leads, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
