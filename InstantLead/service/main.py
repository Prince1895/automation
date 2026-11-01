"""FastAPI intake service for website forms, WhatsApp and Instagram webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from tools.lib.config import Config, get_config
from tools.lib.db import connect, create_event, init_db, queue_counts
from tools.lib.logging import log_info, log_warning, safe_exception
from tools.lib.normalize import form_external_id, meta_event_slices
from tools.lib.replies import reply_metrics

from .scheduler import start_scheduler
from .worker import start_worker

MAX_BODY_BYTES = 1_000_000


def _verify_meta_signature(raw: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_app(config: Config | None = None, *, start_background: bool | None = None) -> FastAPI:
    settings = config or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.db_path)
        stop_event = threading.Event()
        app.state.stop_event = stop_event
        threads = []
        if start_background is not False and settings.worker_enabled:
            threads.append(start_worker(settings, stop_event))
        if start_background is not False and settings.scheduler_enabled:
            threads.append(start_scheduler(settings, stop_event))
        log_info("service", "service started", background_threads=len(threads))
        try:
            yield
        finally:
            stop_event.set()
            for thread in threads:
                thread.join(timeout=5)
            log_info("service", "service stopped")

    app = FastAPI(
        title="InstantLead",
        version="1.0.0",
        description="Lead intake for forms, WhatsApp, Instagram and email enquiries.",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    def healthz() -> Any:
        try:
            conn = connect(settings.db_path)
            try:
                counts = queue_counts(conn)
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                metrics = reply_metrics(conn, settings)
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            log_warning("healthz", "database health check failed", error=safe_exception(exc))
            return JSONResponse(
                {
                    "ok": False,
                    "dry_run": settings.dry_run,
                    "error": "database unavailable",
                    "time": datetime_now(),
                },
                status_code=503,
            )
        backups = sorted(settings.backup_dir.glob("instantlead-*.db")) if settings.backup_dir.exists() else []
        return {
            "ok": True,
            "dry_run": settings.dry_run,
            "queue": counts,
            "dead_letter": counts.get("dead", 0),
            "pending_replies": metrics["pending"],
            "first_reply": metrics,
            "wal": str(journal_mode).lower() == "wal",
            "last_backup": backups[-1].name if backups else None,
            "time": datetime_now(),
        }

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "InstantLead",
            "health": "/healthz",
            "form_webhook": "POST /webhooks/form",
            "meta_webhook": "POST /webhooks/meta",
        }

    @app.get("/webhooks/meta")
    def meta_verify(request: Request) -> Response:
        params = request.query_params
        if params.get("hub.mode") != "subscribe":
            return PlainTextResponse("bad request", status_code=400)
        if not settings.meta_verify_token:
            return PlainTextResponse("META_VERIFY_TOKEN not configured", status_code=503)
        if not hmac.compare_digest(params.get("hub.verify_token", ""), settings.meta_verify_token):
            return PlainTextResponse("forbidden", status_code=403)
        return PlainTextResponse(params.get("hub.challenge", ""))

    @app.post("/webhooks/meta")
    async def meta_webhook(request: Request) -> Response:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse({"ok": False, "error": "payload too large"}, status_code=413)
        if not settings.meta_app_secret:
            return JSONResponse(
                {"ok": False, "error": "META_APP_SECRET not configured"}, status_code=503
            )
        if not _verify_meta_signature(
            raw, request.headers.get("x-hub-signature-256"), settings.meta_app_secret
        ):
            log_warning("webhook", "rejected Meta webhook with invalid signature")
            return JSONResponse({"ok": False, "error": "invalid signature"}, status_code=403)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        events = meta_event_slices(payload)
        conn = connect(settings.db_path)
        queued = 0
        try:
            for source, external_id, sliced in events:
                _, created = create_event(
                    conn, source=source, external_id=external_id, payload=sliced
                )
                queued += int(created)
        finally:
            conn.close()
        log_info("webhook", "Meta webhook accepted", object=payload.get("object"), queued=queued)
        return JSONResponse({"ok": True, "queued": queued})

    @app.post("/webhooks/form")
    async def form_webhook(request: Request) -> Response:
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse({"ok": False, "error": "payload too large"}, status_code=413)
        if not settings.form_webhook_secret:
            return JSONResponse(
                {"ok": False, "error": "FORM_WEBHOOK_SECRET not configured"}, status_code=503
            )
        token = request.headers.get("x-webhook-token") or request.query_params.get("token", "")
        signature = request.headers.get("x-signature-256")
        token_ok = bool(token) and hmac.compare_digest(token, settings.form_webhook_secret)
        signature_ok = False
        if signature:
            expected = "sha256=" + hmac.new(
                settings.form_webhook_secret.encode("utf-8"), raw, hashlib.sha256
            ).hexdigest()
            signature_ok = hmac.compare_digest(expected, signature)
        if not token_ok and not signature_ok:
            log_warning("webhook", "rejected form webhook with invalid token")
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "payload must be an object"}, status_code=400)
        external_id = form_external_id(payload)
        conn = connect(settings.db_path)
        try:
            _, created = create_event(
                conn, source="form", external_id=external_id, payload=payload
            )
        finally:
            conn.close()
        log_info("webhook", "form webhook accepted", queued=int(created))
        return JSONResponse({"ok": True, "queued": int(created)})

    return app


def datetime_now() -> str:
    from tools.lib.util import iso_utc

    return iso_utc()


app = create_app()
