"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamRun } from "@/lib/api";
import type {
  JudgeBreakdown,
  Message,
  RubricCriterion,
  RunSummary,
  Task,
} from "@/lib/types";

// READ THIS BEFORE EDITING THIS FILE:  ./AGENTS.md
// (single-page app, state lives at the top, dual completion paths SSE+poll, etc.)

type Mode = "idle" | "viewing-saved" | "running" | "done";

export default function Page() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [breakdown, setBreakdown] = useState<JudgeBreakdown | null>(null);
  const [activeRubric, setActiveRubric] = useState<RubricCriterion[] | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [status, setStatus] = useState<string>(""); // shown to user during running
  const [error, setError] = useState<string | null>(null);

  // Run IDs that existed when the user pressed "Run fresh". Used by the polling
  // fallback to detect completion if SSE doesn't deliver the `done` event.
  const knownRunIdsBeforeRun = useRef<Set<string>>(new Set());

  // Initial data load.
  useEffect(() => {
    (async () => {
      try {
        const [t, r] = await Promise.all([api.listTasks(), api.listRuns()]);
        setTasks(t);
        setRuns(r);
        if (t.length && !selectedTaskId) setSelectedTaskId(t[0].task_id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedTask = tasks.find((t) => t.task_id === selectedTaskId) ?? null;

  // Update the rubric pane when the task changes (and we're not viewing a saved run with its own rubric).
  useEffect(() => {
    if (mode === "viewing-saved") return;
    setActiveRubric(selectedTask?.rubric ?? null);
  }, [selectedTask, mode]);

  // Polling fallback: while a rollout is running, refresh the saved-runs list every
  // 3 seconds. If a NEW run appears (one that wasn't there when we started), the
  // backend has finished — auto-load it. This catches the case where SSE events
  // didn't make it to the client (proxy buffering, parse hiccup, etc.).
  useEffect(() => {
    if (mode !== "running") return;
    let cancelled = false;
    const tick = async () => {
      try {
        const fresh = await api.listRuns();
        if (cancelled) return;
        setRuns(fresh);
        const before = knownRunIdsBeforeRun.current;
        const newRun = fresh.find((r) => !before.has(r.id));
        if (newRun) {
          // Auto-load the just-finished run.
          await loadSavedRun(newRun.id);
        }
      } catch {
        /* ignore — keep polling */
      }
    };
    const interval = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // loadSavedRun is referenced; safe because it doesn't depend on props.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  async function loadSavedRun(runId: string) {
    setError(null);
    setMode("viewing-saved");
    setStatus("");
    setSelectedRunId(runId);
    setMessages([]);
    setBreakdown(null);
    try {
      const detail = await api.getRun(runId);
      setMessages(detail.messages);
      setBreakdown(detail.judge_breakdown);
      setActiveRubric(detail.rubric ?? selectedTask?.rubric ?? null);
      if (detail.task_id) setSelectedTaskId(detail.task_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setMode("idle");
    }
  }

  async function runFresh() {
    if (!selectedTaskId) return;
    setError(null);
    setMode("running");
    setStatus("Starting…");
    setSelectedRunId(null);
    setMessages([]);
    setBreakdown(null);
    setActiveRubric(selectedTask?.rubric ?? null);
    knownRunIdsBeforeRun.current = new Set(runs.map((r) => r.id));

    try {
      for await (const evt of streamRun({ task_id: selectedTaskId })) {
        if (evt.type === "info") {
          const s = (evt as { status?: string }).status ?? "";
          if (s === "starting") setStatus("Starting…");
          else if (s === "running") setStatus("Running rollout (this can take 15–60s)…");
          else if (s) setStatus(s);
        } else if (evt.type === "message") {
          // First message arriving = transcript replay began
          setStatus("Streaming transcript…");
          setMessages((prev) => [...prev, { role: evt.role, content: evt.content }]);
        } else if (evt.type === "done") {
          setBreakdown(evt.judge_breakdown);
          setMode("done");
          setStatus("");
          api.listRuns().then(setRuns).catch(() => {});
        } else if (evt.type === "error") {
          setError(evt.error);
          setMode("idle");
          setStatus("");
        }
      }
    } catch (e) {
      // SSE failed but the backend may still be running and will save on its own.
      // The polling effect above will pick up the new run when it lands.
      setError(`Streaming failed (will retry via polling): ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <main className="h-screen flex flex-col">
      <header className="border-b border-[var(--color-border)] px-6 py-3 flex items-baseline gap-4">
        <h1 className="text-xl font-semibold">TeachingBench</h1>
        <span className="text-sm text-[var(--color-text-dim)]">Agent teaching eval</span>
      </header>

      {error && (
        <div className="bg-red-900/30 border-b border-red-700 px-6 py-2 text-sm">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* Left half: task selector + rubric + runs list */}
        <aside className="w-1/2 border-r border-[var(--color-border)] flex flex-col min-h-0">
          <Section title="Task">
            <select
              className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-3 py-2"
              value={selectedTaskId ?? ""}
              onChange={(e) => {
                setSelectedTaskId(e.target.value);
                setMode("idle");
                setStatus("");
                setMessages([]);
                setBreakdown(null);
                setSelectedRunId(null);
              }}
            >
              {tasks.map((t) => (
                <option key={t.task_id} value={t.task_id}>
                  {t.task_id} — {t.topic}
                </option>
              ))}
            </select>
            {selectedTask && (
              <div className="mt-3 text-sm text-[var(--color-text-dim)] flex gap-4 flex-wrap">
                <span>
                  turns: <strong className="text-[var(--color-text)]">{selectedTask.turns}</strong>
                </span>
                <span>
                  difficulty: <strong className="text-[var(--color-text)]">{selectedTask.difficulty}</strong>
                </span>
                <span>
                  materials: <strong className="text-[var(--color-text)]">{selectedTask.has_materials ? "yes" : "none"}</strong>
                </span>
              </div>
            )}
            {selectedTask && (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-[var(--color-accent)]">seed question</summary>
                <pre className="mt-2 whitespace-pre-wrap">{selectedTask.seed_question}</pre>
              </details>
            )}
            <button
              onClick={runFresh}
              disabled={!selectedTaskId || mode === "running"}
              className="mt-4 w-full bg-[var(--color-accent)] text-black font-semibold py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90"
            >
              {mode === "running" ? "Running…" : "Run fresh rollout"}
            </button>
          </Section>

          <Section title="Rubric" scroll>
            {activeRubric ? (
              <RubricView rubric={activeRubric} scores={breakdown?.scores ?? null} />
            ) : (
              <p className="text-[var(--color-text-dim)] text-sm">
                Pick a task or saved run to see its rubric.
              </p>
            )}
          </Section>

          <Section title="Saved runs" scroll>
            <RunsList runs={runs} selectedRunId={selectedRunId} onSelect={loadSavedRun} />
          </Section>
        </aside>

        {/* Right half: chat + scores */}
        <section className="w-1/2 flex flex-col min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-4">
            <ChatView messages={messages} mode={mode} status={status} />
          </div>
          <div className="border-t border-[var(--color-border)] px-6 py-3">
            <ScorePanel breakdown={breakdown} />
          </div>
        </section>
      </div>
    </main>
  );
}

function Section({
  title,
  children,
  scroll,
}: {
  title: string;
  children: React.ReactNode;
  scroll?: boolean;
}) {
  return (
    <div
      className={`border-b border-[var(--color-border)] px-6 py-4 ${
        scroll ? "flex-1 min-h-0 overflow-y-auto" : ""
      }`}
    >
      <h2 className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-3">{title}</h2>
      {children}
    </div>
  );
}

// --- Rubric ----------------------------------------------------------------

function RubricView({
  rubric,
  scores,
}: {
  rubric: RubricCriterion[];
  scores: Record<string, number | null> | null;
}) {
  return (
    <div className="space-y-3">
      {rubric.map((c) => {
        const scored = !!scores && c.id in scores;
        const score = scored ? (scores![c.id] as number | null) : undefined;
        return (
          <article
            key={c.id}
            className="border border-[var(--color-border)] bg-[var(--color-panel)] rounded-md p-3"
          >
            <header className="flex items-baseline gap-2 mb-1.5">
              <h3 className="font-semibold text-[var(--color-text)]">{c.id}</h3>
              {scored && <ScoreBadge value={score === undefined ? null : score} />}
            </header>
            <p className="text-xs text-[var(--color-text-dim)] leading-relaxed mb-2">
              {c.description}
            </p>
            {c.anchors?.length ? <AnchorList anchors={c.anchors} /> : null}
          </article>
        );
      })}
    </div>
  );
}

function AnchorList({ anchors }: { anchors: { score: number | null; meaning: string }[] }) {
  // Order: null first (N/A), then descending numeric.
  const sorted = [...anchors].sort((a, b) => {
    if (a.score === null && b.score === null) return 0;
    if (a.score === null) return -1;
    if (b.score === null) return 1;
    return b.score - a.score;
  });
  return (
    <div className="rounded overflow-hidden border border-[var(--color-border)]">
      {sorted.map((a, i) => (
        <div
          key={i}
          className="flex items-stretch text-xs border-t border-[var(--color-border)] first:border-t-0"
          style={{ background: anchorRowBg(a.score) }}
        >
          <div
            className="px-2 py-1.5 font-mono w-14 shrink-0 text-center border-r border-[var(--color-border)] flex items-center justify-center"
            style={{ color: anchorScoreText(a.score) }}
          >
            {a.score === null ? "null" : a.score.toFixed(2)}
          </div>
          <div className="px-3 py-1.5 leading-snug text-[var(--color-text)]">{a.meaning}</div>
        </div>
      ))}
    </div>
  );
}

function anchorRowBg(score: number | null): string {
  if (score === null) return "rgba(138, 146, 158, 0.06)"; // dim gray tint
  if (score >= 0.75) return "rgba(90, 213, 138, 0.10)"; // green
  if (score >= 0.4) return "rgba(243, 201, 105, 0.10)"; // amber
  return "rgba(229, 115, 115, 0.10)"; // red
}

function anchorScoreText(score: number | null): string {
  if (score === null) return "var(--color-text-dim)";
  if (score >= 0.75) return "var(--color-good)";
  if (score >= 0.4) return "var(--color-warn)";
  return "var(--color-bad)";
}

// --- Score badge (used in rubric, runs list, score panel) ------------------

function ScoreBadge({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-panel-hover)] text-[var(--color-text-dim)]">
        null (N/A)
      </span>
    );
  }
  const color =
    value >= 0.75 ? "var(--color-good)" : value >= 0.4 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <span className="text-xs px-2 py-0.5 rounded font-mono" style={{ backgroundColor: color, color: "#000" }}>
      {value.toFixed(2)}
    </span>
  );
}

// --- Saved runs list -------------------------------------------------------

function RunsList({
  runs,
  selectedRunId,
  onSelect,
}: {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelect: (id: string) => void;
}) {
  if (!runs.length) {
    return (
      <p className="text-[var(--color-text-dim)] text-sm">
        No saved runs yet. Run fresh to create one.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {runs.map((r) => {
        const active = r.id === selectedRunId;
        return (
          <li key={r.id}>
            <button
              onClick={() => onSelect(r.id)}
              className={`w-full text-left text-sm px-3 py-2 rounded border ${
                active
                  ? "border-[var(--color-accent)] bg-[var(--color-panel-hover)]"
                  : "border-transparent hover:bg-[var(--color-panel-hover)]"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-xs text-[var(--color-text-dim)]">
                  {r.timestamp}
                </span>
                <ScoreBadge value={r.composite} />
              </div>
              <div className="mt-1 truncate">
                {r.task_id ?? "?"}{" "}
                <span className="text-[var(--color-text-dim)]">— Teacher: {r.model}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// --- Chat ------------------------------------------------------------------

function ChatView({
  messages,
  mode,
  status,
}: {
  messages: Message[];
  mode: Mode;
  status: string;
}) {
  if (!messages.length) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--color-text-dim)] text-sm">
        {mode === "running" ? (
          <span>
            <span className="animate-pulse">●</span> {status || "Working…"}
          </span>
        ) : (
          "Pick a saved run or run fresh to see the transcript here."
        )}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} />
      ))}
      {mode === "running" && (
        <div className="text-xs text-[var(--color-text-dim)] animate-pulse">
          {status || "…"}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const role = message.role;
  const labelMap: Record<string, string> = {
    user: "Student",
    assistant: "Tutor",
    system: "System",
    tool: "Tool",
  };
  const label = labelMap[role] ?? role;
  const align =
    role === "assistant"
      ? "border-[var(--color-accent)]"
      : role === "user"
      ? "border-[var(--color-good)]"
      : "border-[var(--color-border)]";
  return (
    <div className={`border-l-2 pl-3 ${align}`}>
      <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
        {label}
      </div>
      <Markdown content={message.content} />
    </div>
  );
}

function Markdown({ content }: { content: string }) {
  return (
    <div className="md-content text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

// --- Score panel -----------------------------------------------------------

function ScorePanel({ breakdown }: { breakdown: JudgeBreakdown | null }) {
  if (!breakdown || !breakdown.scores) {
    return (
      <p className="text-sm text-[var(--color-text-dim)]">
        Scores will appear here when a rollout completes.
      </p>
    );
  }
  const composite = breakdown.composite;
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-3">
        <span className="text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
          Composite
        </span>
        {composite !== undefined && composite !== null ? (
          <ScoreBadge value={composite} />
        ) : (
          <span className="text-[var(--color-text-dim)]">—</span>
        )}
      </div>
      <div className="flex gap-3 flex-wrap">
        {Object.entries(breakdown.scores).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5 text-sm">
            <span className="text-[var(--color-text-dim)]">{k}</span>
            <ScoreBadge value={v as number | null} />
          </div>
        ))}
      </div>
      {breakdown.rationale && (
        <details className="text-sm mt-2">
          <summary className="cursor-pointer text-[var(--color-accent)]">judge rationale</summary>
          <div className="mt-2 text-[var(--color-text-dim)]">
            <Markdown content={breakdown.rationale} />
          </div>
        </details>
      )}
    </div>
  );
}
