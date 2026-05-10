"use client";

import { useEffect, useState } from "react";
import { api, streamRun } from "@/lib/api";
import type {
  JudgeBreakdown,
  Message,
  RubricCriterion,
  RunSummary,
  Task,
} from "@/lib/types";

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
  const [error, setError] = useState<string | null>(null);

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

  async function loadSavedRun(runId: string) {
    setError(null);
    setMode("viewing-saved");
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
    setSelectedRunId(null);
    setMessages([]);
    setBreakdown(null);
    setActiveRubric(selectedTask?.rubric ?? null);

    try {
      for await (const evt of streamRun({ task_id: selectedTaskId })) {
        if (evt.type === "message") {
          setMessages((prev) => [...prev, { role: evt.role, content: evt.content }]);
        } else if (evt.type === "done") {
          setBreakdown(evt.judge_breakdown);
          setMode("done");
          // Refresh saved-runs list — the backend just appended one.
          api.listRuns().then(setRuns).catch(() => {});
        } else if (evt.type === "error") {
          setError(evt.error);
          setMode("idle");
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setMode("idle");
    }
  }

  return (
    <main className="h-screen flex flex-col">
      <header className="border-b border-[var(--color-border)] px-6 py-3 flex items-baseline gap-4">
        <h1 className="text-xl font-semibold">TeachingBench</h1>
        <span className="text-sm text-[var(--color-text-dim)]">
          LLM teaching-quality eval — single-page dashboard
        </span>
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
                <span>turns: <strong className="text-[var(--color-text)]">{selectedTask.turns}</strong></span>
                <span>difficulty: <strong className="text-[var(--color-text)]">{selectedTask.difficulty}</strong></span>
                <span>materials: <strong className="text-[var(--color-text)]">{selectedTask.has_materials ? "yes" : "none"}</strong></span>
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
              <p className="text-[var(--color-text-dim)] text-sm">Pick a task or saved run to see its rubric.</p>
            )}
          </Section>

          <Section title="Saved runs" scroll>
            <RunsList runs={runs} selectedRunId={selectedRunId} onSelect={loadSavedRun} />
          </Section>
        </aside>

        {/* Right half: chat + scores */}
        <section className="w-1/2 flex flex-col min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-4">
            <ChatView messages={messages} mode={mode} />
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
      <h2 className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-3">
        {title}
      </h2>
      {children}
    </div>
  );
}

function RubricView({
  rubric,
  scores,
}: {
  rubric: RubricCriterion[];
  scores: Record<string, number | null> | null;
}) {
  return (
    <ul className="space-y-3">
      {rubric.map((c) => {
        const score = scores?.[c.id];
        const scored = scores && c.id in scores;
        return (
          <li key={c.id} className="text-sm">
            <div className="flex items-baseline gap-2">
              <strong className="text-[var(--color-text)]">{c.id}</strong>
              {scored && (
                <ScoreBadge value={score === null ? null : (score as number)} />
              )}
            </div>
            <p className="text-[var(--color-text-dim)] text-xs mt-1 leading-relaxed">
              {c.description}
            </p>
            {c.anchors?.length ? (
              <ul className="mt-1 text-xs space-y-0.5">
                {c.anchors.map((a, i) => (
                  <li key={i} className="text-[var(--color-text-dim)]">
                    <span className="font-mono text-[var(--color-text)]">
                      {a.score === null ? "null" : a.score.toFixed(2)}
                    </span>{" "}
                    — {a.meaning}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function ScoreBadge({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-panel-hover)] text-[var(--color-text-dim)]">
        null (N/A)
      </span>
    );
  }
  const color =
    value >= 0.8 ? "var(--color-good)" : value >= 0.5 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <span
      className="text-xs px-2 py-0.5 rounded font-mono"
      style={{ backgroundColor: color, color: "#000" }}
    >
      {value.toFixed(2)}
    </span>
  );
}

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
                {r.task_id ?? "?"} — <span className="text-[var(--color-text-dim)]">{r.model}</span>
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function ChatView({ messages, mode }: { messages: Message[]; mode: Mode }) {
  if (!messages.length) {
    return (
      <div className="h-full flex items-center justify-center text-[var(--color-text-dim)] text-sm">
        {mode === "running"
          ? "Running rollout…"
          : "Pick a saved run or run fresh to see the transcript here."}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} />
      ))}
      {mode === "running" && (
        <div className="text-xs text-[var(--color-text-dim)] animate-pulse">…</div>
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
      <div className="text-sm whitespace-pre-wrap">{message.content}</div>
    </div>
  );
}

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
          <p className="mt-2 text-[var(--color-text-dim)] whitespace-pre-wrap">
            {breakdown.rationale}
          </p>
        </details>
      )}
    </div>
  );
}
