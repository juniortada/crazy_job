"""FastAPI dashboard adapter — APIRouter + Jinja2 + HTMX."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from crazyjob.dashboard.adapters.base import DashboardAdapter

if TYPE_CHECKING:
    from crazyjob.dashboard.core.actions import DashboardActions
    from crazyjob.dashboard.core.queries import DashboardQueries

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


class FastAPIDashboardAdapter(DashboardAdapter):
    """FastAPI APIRouter adapter for the CrazyJob dashboard."""

    def __init__(
        self,
        queries: DashboardQueries,
        actions: DashboardActions,
        url_prefix: str = "/crazyjob",
    ) -> None:
        super().__init__(queries, actions)
        self._url_prefix = url_prefix

    def get_mountable(self) -> Any:
        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse, RedirectResponse
        from fastapi.templating import Jinja2Templates

        router = APIRouter(tags=["crazyjob-dashboard"])
        templates = Jinja2Templates(directory=TEMPLATES_DIR)
        queries = self.q
        actions = self.a
        url_prefix = self._url_prefix

        def _base_url() -> str:
            prefix = url_prefix.rstrip("/")
            return f"{prefix}/"

        def _ctx(request: Request, **kwargs: Any) -> dict[str, Any]:
            """Build template context with base_url and flash messages."""
            flash = request.query_params.get("flash")
            flash_type = request.query_params.get("flash_type", "success")
            flash_messages = [(flash_type, flash)] if flash else []
            return {
                "request": request,
                "base_url": _base_url(),
                "flash_messages": flash_messages,
                **kwargs,
            }

        # ── Read routes ──────────────────────────────────────────────────

        @router.get("/", response_class=HTMLResponse)
        def overview(request: Request) -> Any:
            stats = queries.overview_stats()
            return templates.TemplateResponse("crazyjob/overview.html", _ctx(request, stats=stats))

        @router.get("/queues", response_class=HTMLResponse)
        def queues_page(request: Request) -> Any:
            jobs = queries.list_jobs(status="enqueued")
            return templates.TemplateResponse("crazyjob/queues.html", _ctx(request, jobs=jobs))

        @router.get("/active", response_class=HTMLResponse)
        def active(request: Request) -> Any:
            jobs = queries.list_jobs(status="active")
            return templates.TemplateResponse("crazyjob/active.html", _ctx(request, jobs=jobs))

        @router.get("/scheduled", response_class=HTMLResponse)
        def scheduled(request: Request) -> Any:
            jobs = queries.list_jobs(status="scheduled")
            return templates.TemplateResponse("crazyjob/scheduled.html", _ctx(request, jobs=jobs))

        @router.get("/retrying", response_class=HTMLResponse)
        def retrying(request: Request) -> Any:
            jobs = queries.list_jobs(status="retrying")
            return templates.TemplateResponse("crazyjob/retrying.html", _ctx(request, jobs=jobs))

        @router.get("/completed", response_class=HTMLResponse)
        def completed(request: Request) -> Any:
            jobs = queries.list_jobs(status="completed")
            return templates.TemplateResponse("crazyjob/completed.html", _ctx(request, jobs=jobs))

        @router.get("/failed", response_class=HTMLResponse)
        def failed(request: Request) -> Any:
            jobs = queries.list_jobs(status="failed")
            return templates.TemplateResponse("crazyjob/failed.html", _ctx(request, jobs=jobs))

        @router.get("/dead", response_class=HTMLResponse)
        def dead(request: Request) -> Any:
            dead_letters = queries.list_dead_letters()
            return templates.TemplateResponse(
                "crazyjob/dead.html", _ctx(request, dead_letters=dead_letters)
            )

        @router.get("/workers", response_class=HTMLResponse)
        def workers(request: Request) -> Any:
            worker_list = queries.list_workers()
            return templates.TemplateResponse(
                "crazyjob/workers.html", _ctx(request, workers=worker_list)
            )

        @router.get("/schedules", response_class=HTMLResponse)
        def schedules(request: Request) -> Any:
            schedule_list = queries.list_schedules()
            return templates.TemplateResponse(
                "crazyjob/schedules.html", _ctx(request, schedules=schedule_list)
            )

        # ── Action routes ────────────────────────────────────────────────

        def _redirect(path: str, flash_msg: str, flash_type: str = "success") -> Any:
            url = f"{url_prefix}/{path}?flash={quote(flash_msg)}&flash_type={flash_type}"
            return RedirectResponse(url=url, status_code=303)

        @router.post("/dead/{dead_id}/resurrect")
        def resurrect(dead_id: str) -> Any:
            new_id = actions.resurrect(dead_id)
            return _redirect("dead", f"Job re-enqueued as {new_id}")

        @router.post("/dead/resurrect-all")
        def resurrect_all() -> Any:
            count = actions.bulk_resurrect()
            return _redirect("dead", f"Resurrected {count} dead jobs")

        @router.post("/jobs/{job_id}/cancel")
        def cancel(job_id: str) -> Any:
            actions.cancel(job_id)
            return _redirect("queues", f"Job {job_id} cancelled")

        @router.post("/queues/{queue_name}/pause")
        def pause_queue(queue_name: str) -> Any:
            actions.pause_queue(queue_name)
            return _redirect("queues", f"Queue '{queue_name}' paused")

        @router.post("/queues/{queue_name}/resume")
        def resume_queue(queue_name: str) -> Any:
            actions.resume_queue(queue_name)
            return _redirect("queues", f"Queue '{queue_name}' resumed")

        @router.post("/queues/{queue_name}/clear")
        def clear_queue(queue_name: str) -> Any:
            actions.clear_queue(queue_name)
            return _redirect("queues", f"Queue '{queue_name}' cleared")

        @router.post("/schedules/{schedule_id}/trigger")
        def trigger_schedule(schedule_id: str) -> Any:
            new_id = actions.trigger_schedule(schedule_id)
            return _redirect("schedules", f"Schedule triggered -> job {new_id}")

        return router
