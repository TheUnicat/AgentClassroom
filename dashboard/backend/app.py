"""FastAPI dashboard backend for TeachingBench.

Endpoints:
  - GET  /api/tasks             — list tasks with rubric + metadata
  - GET  /api/runs              — list saved rollouts (summary)
  - GET  /api/runs/{run_id}     — full saved rollout (transcript, scores, rationale)
  - POST /api/run               — trigger fresh rollout, stream via SSE

API key: read from OPENAI_API_KEY env var (server-side; no per-user auth in v0.1).
Saved runs source: configurable via TEACHINGBENCH_RUNS_DIR; default points at the repo's
  environments/teachingbench/outputs/runs/ directory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from verifiers.types import ClientConfig

from teachingbench.dataset import discover_tasks, load_task
from teachingbench.env import load_environment

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="TeachingBench Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- config ----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(
    os.environ.get(
        "TEACHINGBENCH_RUNS_DIR",
        str(REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"),
    )
)
DEFAULT_TUTOR_MODEL = os.environ.get("DEFAULT_TUTOR_MODEL", "gpt-5.4-nano")
DEFAULT_STUDENT_MODEL = os.environ.get("DEFAULT_STUDENT_MODEL", "gpt-5.4-mini")
DEFAULT_JUDGE_MODEL = os.environ.get("DEFAULT_JUDGE_MODEL", "gpt-5.4-nano")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")


# --- /api/tasks ------------------------------------------------------------


@app.get("/api/tasks")
def list_tasks() -> list[dict[str, Any]]:
    """Return all available tasks with rubric, prompts, and metadata."""
    out: list[dict[str, Any]] = []
    for task_dir in discover_tasks():
        loaded = load_task(task_dir)
        out.append(
            {
                "task_id": loaded["task_id"],
                "subject": loaded["subject"],
                "topic": loaded["topic"],
                "difficulty": loaded["difficulty"],
                "turns": loaded["turns"],
                "rubric": loaded["rubric"],
                "seed_question": loaded["seed_question"],
                "has_materials": bool(loaded["materials"]),
                "fixed_followup_count": len(loaded["fixed_student_followups"]),
            }
        )
    return out


# --- /api/runs -------------------------------------------------------------


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    """List saved rollouts (summary). Sorted newest-first by directory name."""
    if not RUNS_DIR.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        results_path = run_dir / "results.jsonl"
        if not results_path.is_file():
            continue
        first = ""
        with results_path.open() as f:
            first = f.readline()
        if not first:
            continue
        try:
            rec = json.loads(first)
        except json.JSONDecodeError:
            continue
        info = _parse_info(rec.get("info"))
        breakdown = rec.get("judge_breakdown") or {}
        runs.append(
            {
                "id": run_dir.name,
                "task_id": info.get("task_id"),
                "topic": info.get("topic"),
                "model": _model_from_run_id(run_dir.name),
                "timestamp": _timestamp_from_run_id(run_dir.name),
                "composite": rec.get("reward", 0.0),
                "scores": breakdown.get("scores") if isinstance(breakdown, dict) else None,
                "rationale": breakdown.get("rationale") if isinstance(breakdown, dict) else None,
            }
        )
    return runs


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Return one saved rollout's full data."""
    if "/" in run_id or ".." in run_id:  # paranoia
        raise HTTPException(400, "Invalid run id")
    run_dir = RUNS_DIR / run_id
    results_path = run_dir / "results.jsonl"
    if not results_path.is_file():
        raise HTTPException(404, f"Run not found: {run_id}")
    with results_path.open() as f:
        line = f.readline()
    rec = json.loads(line)
    info = _parse_info(rec.get("info"))
    return {
        "id": run_id,
        "task_id": info.get("task_id"),
        "topic": info.get("topic"),
        "rubric": info.get("rubric"),
        "messages": _normalize_messages((rec.get("prompt") or []) + (rec.get("completion") or [])),
        "reward": rec.get("reward"),
        "judge_breakdown": rec.get("judge_breakdown"),
        "metrics": rec.get("metrics"),
        "stop_condition": rec.get("stop_condition"),
        "is_completed": rec.get("is_completed"),
    }


# --- /api/run (SSE) --------------------------------------------------------


class RunRequest(BaseModel):
    task_id: str
    tutor_model: str | None = None
    student_model: str | None = None
    judge_model: str | None = None


@app.post("/api/run")
async def run_fresh(req: RunRequest) -> EventSourceResponse:
    """Trigger a fresh rollout. Streams progress via SSE."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, "Server missing OPENAI_API_KEY")

    tutor_model = req.tutor_model or DEFAULT_TUTOR_MODEL
    student_model = req.student_model or DEFAULT_STUDENT_MODEL
    judge_model = req.judge_model or DEFAULT_JUDGE_MODEL

    return EventSourceResponse(
        _run_stream(req.task_id, tutor_model, student_model, judge_model, api_key)
    )


async def _run_stream(
    task_id: str,
    tutor_model: str,
    student_model: str,
    judge_model: str,
    api_key: str,
) -> AsyncIterator[dict[str, Any]]:
    """Run the rollout and emit SSE events.

    NOTE on streaming: verifiers' `evaluate` is monolithic — we don't get per-turn
    callbacks out of the box. v0.1 runs the rollout to completion, then replays the
    transcript message-by-message with a small delay so the UI feels live.
    """
    yield {"event": "info", "data": json.dumps({"status": "starting", "task_id": task_id})}

    env_client = AsyncOpenAI(api_key=api_key, base_url=OPENAI_BASE_URL)
    tutor_client = ClientConfig(
        client_type="openai_chat_completions",
        api_key_var="OPENAI_API_KEY",
        api_base_url=OPENAI_BASE_URL,
    )

    try:
        env = load_environment(
            judge_client=env_client,
            judge_model=judge_model,
            student_client=env_client,
            student_model=student_model,
            task_filter=task_id,
        )
    except Exception as e:
        logger.exception("Env construction failed")
        yield {"event": "error", "data": json.dumps({"error": f"env load: {e}"})}
        return

    yield {"event": "info", "data": json.dumps({"status": "running", "tutor_model": tutor_model, "student_model": student_model, "judge_model": judge_model})}

    try:
        outputs = await env.evaluate(
            client=tutor_client,
            model=tutor_model,
            num_examples=1,
            rollouts_per_example=1,
            state_columns=["judge_breakdown"],
        )
    except Exception as e:
        logger.exception("Rollout failed")
        yield {"event": "error", "data": json.dumps({"error": str(e)})}
        return

    rollouts = outputs.get("outputs", []) if isinstance(outputs, dict) else []
    if not rollouts:
        yield {"event": "error", "data": json.dumps({"error": "No rollout produced"})}
        return

    r = rollouts[0]
    messages = _normalize_messages((r.get("prompt") or []) + (r.get("completion") or []))
    for m in messages:
        yield {"event": "message", "data": json.dumps(m)}
        await asyncio.sleep(0.05)

    breakdown = r.get("judge_breakdown") or {}
    yield {
        "event": "done",
        "data": json.dumps(
            {
                "reward": r.get("reward", 0.0),
                "judge_breakdown": breakdown,
                "stop_condition": r.get("stop_condition"),
                "metrics": r.get("metrics"),
            }
        ),
    }


# --- helpers ---------------------------------------------------------------


def _parse_info(info: Any) -> dict[str, Any]:
    if isinstance(info, dict):
        return info
    if isinstance(info, str):
        try:
            return json.loads(info)
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_messages(msgs: list[Any]) -> list[dict[str, Any]]:
    """Flatten verifiers' Pydantic message types to plain JSON-friendly dicts."""
    out: list[dict[str, Any]] = []
    for m in msgs:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                p.get("text", "") if isinstance(p, dict) else str(getattr(p, "text", p))
                for p in content
            )
        out.append({"role": str(role), "content": str(content or "")})
    return out


def _timestamp_from_run_id(run_id: str) -> str:
    parts = run_id.split("__", 1)
    return parts[0] if parts else run_id


def _model_from_run_id(run_id: str) -> str:
    parts = run_id.rsplit("__", 1)
    return parts[1] if len(parts) > 1 else "?"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "runs_dir": str(RUNS_DIR),
        "runs_dir_exists": RUNS_DIR.is_dir(),
        "openai_key_set": bool(os.environ.get("OPENAI_API_KEY")),
    }
