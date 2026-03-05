"""Flask dashboard adapter — Blueprint + Jinja2 + HTMX."""
from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for

from crazyjob.dashboard.adapters.base import DashboardAdapter
from crazyjob.dashboard.core.actions import DashboardActions
from crazyjob.dashboard.core.queries import DashboardQueries

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def _get_flash_messages() -> list[tuple[str, str]]:
    """Get Flask flash messages as list of (category, message) tuples."""
    try:
        from flask import get_flashed_messages

        return [
            (cat, msg)
            for cat, msg in get_flashed_messages(with_categories=True)
        ]
    except Exception:
        return []


class FlaskDashboardAdapter(DashboardAdapter):
    """Flask Blueprint adapter for the CrazyJob dashboard."""

    def get_mountable(self) -> Blueprint:
        bp = Blueprint(
            "crazyjob_dashboard",
            __name__,
            template_folder=TEMPLATES_DIR,
        )
        self._register_routes(bp)
        return bp

    def _ctx(self, **kwargs: Any) -> dict[str, Any]:
        """Build template context with base_url and flash_messages."""
        base_url = request.script_root + request.url_rule.rule.rsplit("/", 1)[0] + "/"
        # For root route ("/"), base_url is already correct
        if request.url_rule and request.url_rule.rule.endswith("/"):
            base_url = request.url_root.rstrip("/") + url_for(".overview")
            if not base_url.endswith("/"):
                base_url += "/"
        return {
            "base_url": url_for(".overview"),
            "flash_messages": _get_flash_messages(),
            **kwargs,
        }

    def _register_routes(self, bp: Blueprint) -> None:
        queries = self.q
        actions = self.a
        ctx = self._ctx

        @bp.route("/")
        def overview() -> str:
            stats = queries.overview_stats()
            return render_template("crazyjob/overview.html", **ctx(stats=stats))

        @bp.route("/queues")
        def queues() -> str:
            jobs = queries.list_jobs(status="enqueued")
            return render_template("crazyjob/queues.html", **ctx(jobs=jobs))

        @bp.route("/active")
        def active() -> str:
            jobs = queries.list_jobs(status="active")
            return render_template("crazyjob/active.html", **ctx(jobs=jobs))

        @bp.route("/scheduled")
        def scheduled() -> str:
            jobs = queries.list_jobs(status="scheduled")
            return render_template("crazyjob/scheduled.html", **ctx(jobs=jobs))

        @bp.route("/retrying")
        def retrying() -> str:
            jobs = queries.list_jobs(status="retrying")
            return render_template("crazyjob/retrying.html", **ctx(jobs=jobs))

        @bp.route("/completed")
        def completed() -> str:
            jobs = queries.list_jobs(status="completed")
            return render_template("crazyjob/completed.html", **ctx(jobs=jobs))

        @bp.route("/failed")
        def failed() -> str:
            jobs = queries.list_jobs(status="failed")
            return render_template("crazyjob/failed.html", **ctx(jobs=jobs))

        @bp.route("/dead")
        def dead() -> str:
            dead_letters = queries.list_dead_letters()
            return render_template("crazyjob/dead.html", **ctx(dead_letters=dead_letters))

        @bp.route("/workers")
        def workers() -> str:
            worker_list = queries.list_workers()
            return render_template("crazyjob/workers.html", **ctx(workers=worker_list))

        @bp.route("/schedules")
        def schedules() -> str:
            schedule_list = queries.list_schedules()
            return render_template("crazyjob/schedules.html", **ctx(schedules=schedule_list))

        # ── Actions ──────────────────────────────────────────────────────

        @bp.route("/dead/<dead_id>/resurrect", methods=["POST"])
        def resurrect(dead_id: str) -> Any:
            new_id = actions.resurrect(dead_id)
            flash(f"Job re-enqueued as {new_id}", "success")
            return redirect(url_for(".dead"))

        @bp.route("/dead/resurrect-all", methods=["POST"])
        def resurrect_all() -> Any:
            count = actions.bulk_resurrect()
            flash(f"Resurrected {count} dead jobs", "success")
            return redirect(url_for(".dead"))

        @bp.route("/jobs/<job_id>/cancel", methods=["POST"])
        def cancel(job_id: str) -> Any:
            actions.cancel(job_id)
            flash(f"Job {job_id} cancelled", "success")
            return redirect(url_for(".queues"))

        @bp.route("/queues/<queue_name>/pause", methods=["POST"])
        def pause_queue(queue_name: str) -> Any:
            actions.pause_queue(queue_name)
            flash(f"Queue '{queue_name}' paused", "success")
            return redirect(url_for(".queues"))

        @bp.route("/queues/<queue_name>/resume", methods=["POST"])
        def resume_queue(queue_name: str) -> Any:
            actions.resume_queue(queue_name)
            flash(f"Queue '{queue_name}' resumed", "success")
            return redirect(url_for(".queues"))

        @bp.route("/queues/<queue_name>/clear", methods=["POST"])
        def clear_queue(queue_name: str) -> Any:
            actions.clear_queue(queue_name)
            flash(f"Queue '{queue_name}' cleared", "success")
            return redirect(url_for(".queues"))

        @bp.route("/schedules/<schedule_id>/trigger", methods=["POST"])
        def trigger_schedule(schedule_id: str) -> Any:
            new_id = actions.trigger_schedule(schedule_id)
            flash(f"Schedule triggered -> job {new_id}", "success")
            return redirect(url_for(".schedules"))
