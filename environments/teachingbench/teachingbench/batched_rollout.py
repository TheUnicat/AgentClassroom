"""Batched-tutor rollouts via OpenAI Batch API / Anthropic Message Batches API.

Strategy: parallel-across-rollouts, sequential-within-rollout. At each turn N:
  1. Build a batch of every active rollout's turn-N tutor call.
  2. Submit to the provider's Batch endpoint (50% off pricing, 24h SLA — typically
     1–6h for our small batches).
  3. Poll until completion.
  4. For each rollout: append tutor response, then run student inference in
     real-time (gpt-5.4-mini, not batched — cheap, fast, also needs the
     just-arrived tutor response).
  5. Continue to turn N+1 for rollouts not yet at target_turns.

Saves results in the same `results.jsonl` format as `verifiers.env.evaluate` so
`judge_reliability_check.py --n 1` can score them later (also via Batch).

Bypasses verifiers entirely for the tutor side so we can (a) use Batch APIs
and (b) format Anthropic content blocks natively (including cache_control,
though for sequential-across-batches the 5min cache TTL won't help much).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from teachingbench.client_utils import detect_provider
from teachingbench.dataset import build_dataset
from teachingbench.multimodal import _pdf_path_to_blocks, materials_media_to_content_blocks
from teachingbench.student.llm import LLMStudent

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS_ROOT = REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"


# ============================================================================
# Per-rollout state
# ============================================================================


@dataclass
class RolloutState:
    """Tracks one rollout (one task × one model × one replica) across turn-by-turn batching."""

    task_id: str
    model: str
    info: dict[str, Any]
    target_turns: int
    materials_media: list[dict[str, Any]]
    # tutor_messages is the OpenAI-format chat log: [system, user1, assistant1, user2, ...]
    # We translate to Anthropic format at batch-submission time for Anthropic tutors.
    tutor_messages: list[dict[str, Any]] = field(default_factory=list)
    completed_turns: int = 0
    done: bool = False
    error: str | None = None

    @property
    def custom_id(self) -> str:
        # Anthropic + OpenAI both require custom_id matching ^[a-zA-Z0-9_-]+$ and len<64.
        # Use a hash-friendly tag with model/task/replica info. Slug task path.
        slug = self.task_id.replace("/", "_")
        return f"{self._sanitize(self.model)}__{slug}"[:60]

    @staticmethod
    def _sanitize(s: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


# ============================================================================
# Provider-specific helpers
# ============================================================================


def openai_messages_for_state(state: RolloutState) -> list[dict[str, Any]]:
    """OpenAI tutor messages are already in the canonical format on state."""
    return state.tutor_messages


def anthropic_messages_for_state(state: RolloutState) -> tuple[str, list[dict[str, Any]]]:
    """Return (system_text, messages) in Anthropic format.

    Translates `image_url` content blocks to Anthropic `image` blocks. Adds a
    `cache_control: {type: ephemeral}` marker on the LAST image block in the
    seed user message so Anthropic can cache the PDF prefix.
    """
    system_text = ""
    out_msgs: list[dict[str, Any]] = []
    for msg in state.tutor_messages:
        if msg["role"] == "system":
            system_text = msg["content"] if isinstance(msg["content"], str) else _flatten_text(msg["content"])
            continue
        content = msg["content"]
        if isinstance(content, str):
            out_msgs.append({"role": msg["role"], "content": content})
            continue
        # Multipart content
        anth_blocks = []
        image_block_indices: list[int] = []
        for part in content:
            if part.get("type") == "text":
                anth_blocks.append({"type": "text", "text": part["text"]})
            elif part.get("type") == "image_url":
                url = part["image_url"]["url"]
                # url format: data:image/png;base64,<data>
                header, b64 = url.split(",", 1)
                media_type = header.split(":")[1].split(";")[0]
                anth_blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })
                image_block_indices.append(len(anth_blocks) - 1)
        # Add cache_control on the last image (caches the PDF prefix)
        if image_block_indices:
            anth_blocks[image_block_indices[-1]]["cache_control"] = {"type": "ephemeral"}
        out_msgs.append({"role": msg["role"], "content": anth_blocks})
    return system_text, out_msgs


def _flatten_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) and p.get("type") == "text" else "" for p in content)
    return str(content)


# ============================================================================
# Batch submission + polling
# ============================================================================


async def submit_openai_batch(
    client: AsyncOpenAI,
    states: list[RolloutState],
    model: str,
    output_dir: Path,
) -> str:
    """Submit a batch of tutor turn-N calls for OpenAI. Returns batch_id."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / f"batch_input_{model}_{uuid.uuid4().hex[:8]}.jsonl"
    with jsonl_path.open("w") as f:
        for s in states:
            req = {
                "custom_id": s.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": openai_messages_for_state(s),
                    "max_completion_tokens": 2048,
                },
            }
            f.write(json.dumps(req) + "\n")

    with jsonl_path.open("rb") as f:
        file_obj = await client.files.create(file=f, purpose="batch")
    batch = await client.batches.create(
        input_file_id=file_obj.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    return batch.id


async def submit_anthropic_batch(
    client: AsyncAnthropic,
    states: list[RolloutState],
    model: str,
    output_dir: Path,
) -> str:
    """Submit a batch of tutor turn-N calls for Anthropic. Returns batch_id."""
    output_dir.mkdir(parents=True, exist_ok=True)
    requests = []
    for s in states:
        system_text, messages = anthropic_messages_for_state(s)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": 2048,
            "messages": messages,
        }
        if system_text:
            params["system"] = system_text
        requests.append({"custom_id": s.custom_id, "params": params})

    # Save what we submitted for debugging
    (output_dir / f"anth_batch_input_{model}_{uuid.uuid4().hex[:8]}.json").write_text(
        json.dumps([{"custom_id": r["custom_id"], "params_keys": list(r["params"].keys())} for r in requests], indent=2)
    )

    batch = await client.messages.batches.create(requests=requests)
    return batch.id


async def poll_openai_batch(client: AsyncOpenAI, batch_id: str, interval: int = 60) -> Any:
    """Block until an OpenAI batch reaches a terminal state."""
    while True:
        batch = await client.batches.retrieve(batch_id)
        status = batch.status
        if status in ("completed", "failed", "cancelled", "expired"):
            logger.info("OpenAI batch %s terminal: %s", batch_id, status)
            return batch
        logger.info("OpenAI batch %s status=%s (poll in %ds)", batch_id, status, interval)
        await asyncio.sleep(interval)


async def poll_anthropic_batch(client: AsyncAnthropic, batch_id: str, interval: int = 60) -> Any:
    """Block until an Anthropic batch reaches a terminal state."""
    while True:
        batch = await client.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        if status in ("ended", "canceling", "expired"):
            logger.info("Anthropic batch %s terminal: %s", batch_id, status)
            return batch
        logger.info("Anthropic batch %s processing_status=%s (poll in %ds)", batch_id, status, interval)
        await asyncio.sleep(interval)


async def fetch_openai_batch_results(client: AsyncOpenAI, batch: Any) -> dict[str, dict[str, Any]]:
    """Return {custom_id: {text, error}}."""
    if not batch.output_file_id:
        logger.warning("OpenAI batch %s has no output_file_id (status=%s)", batch.id, batch.status)
        return {}
    file_resp = await client.files.content(batch.output_file_id)
    text = file_resp.text if hasattr(file_resp, "text") else file_resp.read().decode()
    results: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        cid = rec["custom_id"]
        response = rec.get("response", {})
        if response.get("status_code") == 200:
            body = response["body"]
            assistant_msg = body["choices"][0]["message"]["content"]
            results[cid] = {"text": assistant_msg, "error": None}
        else:
            results[cid] = {"text": None, "error": rec.get("error") or response.get("status_code")}
    return results


async def fetch_anthropic_batch_results(client: AsyncAnthropic, batch_id: str) -> dict[str, dict[str, Any]]:
    """Return {custom_id: {text, error}}."""
    results: dict[str, dict[str, Any]] = {}
    async for result in await client.messages.batches.results(batch_id):
        cid = result.custom_id
        if result.result.type == "succeeded":
            message = result.result.message
            # Concatenate text blocks
            text_parts = []
            for block in message.content:
                if block.type == "text":
                    text_parts.append(block.text)
            results[cid] = {"text": "\n".join(text_parts), "error": None}
        else:
            results[cid] = {"text": None, "error": str(result.result)}
    return results


# ============================================================================
# Main orchestration
# ============================================================================


async def run_student_turn(student: LLMStudent, state: RolloutState) -> str:
    """Real-time student call. Reuses LLMStudent which handles role flipping."""
    return await student.respond(
        state.tutor_messages,
        topic=state.info.get("topic", ""),
        materials=state.info.get("materials", ""),
        system_prompt=state.info.get("student_system_prompt", ""),
    )


def build_initial_messages(info: dict[str, Any], materials_media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the initial [system, user_seed] messages for a tutor."""
    msgs: list[dict[str, Any]] = []
    sys_prompt = info.get("tutor_system_prompt", "") or ""
    if sys_prompt.strip():
        msgs.append({"role": "system", "content": sys_prompt})
    seed = info.get("seed_question") or info.get("question") or ""
    # We need the seed_question — fall back to the info field if needed
    if materials_media:
        # Build multipart content: [text, image1, image2, ...]
        blocks = materials_media_to_content_blocks(materials_media)
        content = [{"type": "text", "text": seed}] + blocks
        msgs.append({"role": "user", "content": content})
    else:
        msgs.append({"role": "user", "content": seed})
    return msgs


def init_rollout_states(model: str, task_filter: list[str] | None = None) -> list[RolloutState]:
    """Build one RolloutState per task for a given tutor model."""
    states: list[RolloutState] = []
    rows = list(build_dataset())
    for row in rows:
        info = json.loads(row["info"]) if isinstance(row["info"], str) else row["info"]
        if task_filter and info["task_id"] not in task_filter:
            continue
        # The dataset row's `question` field is the seed, but info has it too.
        # Make sure seed_question is present (build_initial_messages uses it).
        info_with_seed = {**info, "seed_question": row["question"]}
        materials_media = info.get("materials_media") or []
        tutor_messages = build_initial_messages(info_with_seed, materials_media)
        states.append(RolloutState(
            task_id=info["task_id"],
            model=model,
            info=info_with_seed,
            target_turns=int(info.get("turns") or 4),
            materials_media=materials_media,
            tutor_messages=tutor_messages,
        ))
    return states


def save_rollout(state: RolloutState, output_dir: Path) -> None:
    """Save a single completed rollout to results.jsonl (verifiers-compatible format)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    # Split into prompt (first user msg + any system) and completion (rest)
    # Verifiers convention: prompt = everything up to and including the FIRST user msg
    prompt: list[dict[str, Any]] = []
    completion: list[dict[str, Any]] = []
    seen_first_user = False
    for m in state.tutor_messages:
        if not seen_first_user and m["role"] in ("system", "user"):
            prompt.append(m)
            if m["role"] == "user":
                seen_first_user = True
        else:
            completion.append(m)

    record = {
        "task": state.task_id,
        "prompt": prompt,
        "completion": completion,
        "info": state.info,
        "reward": 0.0,  # judging deferred
        "judge_breakdown": {"skipped": True, "scores": {}, "weights": {}, "composite": 0.0,
                            "rationale": "batched_rollout: judging deferred", "rubric": []},
        "stop_condition": "turns_reached" if state.done and not state.error else state.error or "incomplete",
        "completed_turns": state.completed_turns,
        "target_turns": state.target_turns,
        "tutor_model": state.model,
        "batched_rollout": True,
        "error": state.error,
    }
    (output_dir / "results.jsonl").write_text(json.dumps(record) + "\n")


async def run_one_model_batched(
    *,
    model: str,
    task_filter: list[str] | None,
    output_root: Path,
    student: LLMStudent,
    openai_client: AsyncOpenAI,
    anthropic_client: AsyncAnthropic,
    poll_interval: int = 60,
) -> None:
    """Run all rollouts for one tutor model via batched tutor calls."""
    provider = detect_provider(model)
    logger.info("Initializing rollouts: model=%s provider=%s", model, provider)

    states = init_rollout_states(model, task_filter=task_filter)
    if not states:
        logger.warning("No tasks for model %s", model)
        return

    logger.info("Active rollouts for %s: %d", model, len(states))
    max_target = max(s.target_turns for s in states)

    batches_dir = output_root / f"batches_{model.replace('/', '_').replace('.', '_')}"

    # Phase loop: one batch per turn, up to max target_turns
    for turn in range(1, max_target + 1):
        # Filter to states that need turn N (i.e., completed_turns < target_turns and not done)
        active = [s for s in states if not s.done and not s.error and s.completed_turns < s.target_turns]
        if not active:
            logger.info("[model=%s] No active rollouts at turn %d — terminating", model, turn)
            break

        logger.info("[model=%s] turn %d: submitting batch for %d rollouts", model, turn, len(active))

        # Submit batch
        try:
            if provider == "openai":
                batch_id = await submit_openai_batch(openai_client, active, model, batches_dir)
            else:
                batch_id = await submit_anthropic_batch(anthropic_client, active, model, batches_dir)
            logger.info("[model=%s] turn %d batch submitted: %s", model, turn, batch_id)
        except Exception as e:
            logger.error("[model=%s] batch submit FAILED at turn %d: %s", model, turn, e)
            for s in active:
                s.error = f"batch submit failed at turn {turn}: {e}"
            break

        # Poll
        try:
            if provider == "openai":
                batch = await poll_openai_batch(openai_client, batch_id, interval=poll_interval)
                if batch.status != "completed":
                    logger.error("[model=%s] batch %s terminal=%s (errors)", model, batch_id, batch.status)
                results = await fetch_openai_batch_results(openai_client, batch)
            else:
                batch = await poll_anthropic_batch(anthropic_client, batch_id, interval=poll_interval)
                if batch.processing_status != "ended":
                    logger.error("[model=%s] batch %s terminal=%s", model, batch_id, batch.processing_status)
                results = await fetch_anthropic_batch_results(anthropic_client, batch_id)
        except Exception as e:
            logger.error("[model=%s] batch poll/fetch FAILED at turn %d: %s", model, turn, e)
            for s in active:
                s.error = f"batch fetch failed at turn {turn}: {e}"
            break

        # Process results: append tutor response, then student response
        for s in active:
            result = results.get(s.custom_id)
            if result is None or result.get("text") is None:
                err = (result or {}).get("error") or "missing from batch results"
                s.error = f"turn {turn} tutor: {err}"
                logger.error("[%s/%s] tutor turn %d FAILED: %s", model, s.task_id, turn, err)
                continue
            # Append tutor response
            s.tutor_messages.append({"role": "assistant", "content": result["text"]})
            s.completed_turns += 1
            if s.completed_turns >= s.target_turns:
                s.done = True
                continue
            # Run student inference real-time
            try:
                student_msg = await run_student_turn(student, s)
            except Exception as e:
                s.error = f"turn {turn} student: {e}"
                logger.error("[%s/%s] student after tutor turn %d FAILED: %s", model, s.task_id, turn, e)
                continue
            s.tutor_messages.append({"role": "user", "content": student_msg})

        # Persist progress per rollout after each phase (so a crash mid-batch is recoverable in principle)
        for s in states:
            cell_dir = output_root / f"{model}__{s.task_id.replace('/', '__')}"
            save_rollout(s, cell_dir)

        done_count = sum(1 for s in states if s.done)
        err_count = sum(1 for s in states if s.error)
        logger.info("[model=%s] after turn %d: done=%d errors=%d active_next=%d",
                    model, turn, done_count, err_count, len(states) - done_count - err_count)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tutor-models", required=True, nargs="+", help="Models to run, in order.")
    p.add_argument("--task-ids", nargs="+", default=None, help='List of task IDs, or omit for all 57.')
    p.add_argument("--task-list-file", default=None, help='Path to a file with one task ID per line. Overrides --task-ids if given.')
    p.add_argument("--student-model", default="gpt-5.4-mini")
    p.add_argument("--openai-api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--anthropic-api-key-env", default="ANTHROPIC_API_KEY")
    p.add_argument("--output-root", default=None)
    p.add_argument("--poll-interval", type=int, default=60, help="Polling interval (seconds). Default 60.")
    return p.parse_args()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    openai_key = os.environ.get(args.openai_api_key_env)
    anthropic_key = os.environ.get(args.anthropic_api_key_env)
    if not openai_key:
        sys.exit(f"${args.openai_api_key_env} is not set")

    needs_anth = any(detect_provider(m) == "anthropic" for m in args.tutor_models)
    if needs_anth and not anthropic_key:
        sys.exit(f"${args.anthropic_api_key_env} is not set (needed for claude-* tutors)")

    openai_client = AsyncOpenAI(api_key=openai_key)
    anthropic_client = AsyncAnthropic(api_key=anthropic_key) if anthropic_key else None
    student = LLMStudent(client=openai_client, model=args.student_model)

    # Resolve task list (file overrides --task-ids list)
    if args.task_list_file:
        task_ids = [
            line.strip() for line in Path(args.task_list_file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    else:
        # Also handle the case where --task-ids got passed a single space-joined string
        # (zsh / shell quirks). Flatten by splitting on whitespace if any item has spaces.
        task_ids = args.task_ids
        if task_ids and any(" " in t for t in task_ids):
            flat: list[str] = []
            for t in task_ids:
                flat.extend(t.split())
            task_ids = flat
            logger.info("Flattened space-joined --task-ids into %d items", len(task_ids))

    if args.output_root:
        output_root = Path(args.output_root)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_root = DEFAULT_RUNS_ROOT / f"batched_{ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    plan = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tutor_models": args.tutor_models,
        "task_ids": task_ids,
        "n_tasks": len(task_ids) if task_ids else 0,
        "student_model": args.student_model,
        "output_root": str(output_root),
    }
    (output_root / "batched_plan.json").write_text(json.dumps(plan, indent=2))
    logger.info("Plan: %s", json.dumps(plan, indent=2))

    for model in args.tutor_models:
        logger.info("==== Starting model: %s ====", model)
        await run_one_model_batched(
            model=model,
            task_filter=task_ids,
            output_root=output_root,
            student=student,
            openai_client=openai_client,
            anthropic_client=anthropic_client,
            poll_interval=args.poll_interval,
        )
        logger.info("==== Finished model: %s ====", model)

    logger.info("All done. Results at %s", output_root)


if __name__ == "__main__":
    asyncio.run(main())
