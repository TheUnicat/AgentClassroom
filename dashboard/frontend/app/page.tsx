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

type Mode = "idle" | "viewing-saved" | "running" | "done";
type View = "inspect" | "results" | "report";

// Fixed teacher-model palette + display names. Keep in sync with the chart palette.
const TEACHER_MODELS: { id: string; display: string; color: string }[] = [
  { id: "gpt-5.4-nano", display: "GPT-5.4-nano", color: "#ef4444" },
  { id: "gpt-5.4-mini", display: "GPT-5.4-mini", color: "#3b82f6" },
  { id: "gpt-5.4",      display: "GPT-5.4",      color: "#10b981" },
  { id: "claude-opus-4-7", display: "Opus 4.7",  color: "#f59e0b" },
];
const MODEL_DISPLAY: Record<string, string> = Object.fromEntries(
  TEACHER_MODELS.map((m) => [m.id, m.display]),
);
const MODEL_COLOR: Record<string, string> = Object.fromEntries(
  TEACHER_MODELS.map((m) => [m.id, m.color]),
);

function displayModel(id: string | null | undefined): string {
  if (!id) return "?";
  return MODEL_DISPLAY[id] ?? id;
}

// Hardcoded judge model display — the saved 228-rollout batch used GPT-5.4 as judge.
// For fresh rollouts we'll override with the actual configured judge if surfaced.
const DEFAULT_JUDGE_DISPLAY = "GPT-5.4";

// Convert "factual_correctness" → "Factual Correctness", "answers_the_question" → "Answers the Question".
function prettyCriterionId(id: string): string {
  const words = id.split("_");
  return words
    .map((w, i) => {
      if (i > 0 && ["the", "a", "an", "of", "to", "for", "in"].includes(w)) return w;
      return w.charAt(0).toUpperCase() + w.slice(1);
    })
    .join(" ");
}

// Convert "cs/halting_problem" → "How does the halting problem work?"
// Falls back to a Title Case version if a question form doesn't fit.
function prettyTaskName(task: Task): string {
  // Strip subject prefix.
  const raw = task.task_id.includes("/") ? task.task_id.split("/").slice(1).join("/") : task.task_id;
  const words = raw.split("_").join(" ");
  // Heuristic: phrase as a question.
  const lower = words.toLowerCase();
  // Patterns where a question feels natural:
  if (/^(intro|introduction|basics?) /.test(lower)) {
    return `What are the basics of ${lower.replace(/^(intro(?:duction)?|basics?) /, "")}?`;
  }
  if (lower.endsWith(" misconception") || lower.includes(" misconception")) {
    return `What's the misconception about ${lower.replace(/ misconception.*/, "")}?`;
  }
  if (/(vs|versus)/.test(lower)) {
    return `What's the difference: ${titleCase(lower.replace(/_/g, " "))}?`;
  }
  if (/^(why|how|what|when|where|which|is|are|does|do|can|should)\b/.test(lower)) {
    return capitalize(lower).replace(/\?*$/, "?");
  }
  // Default: phrase as "How does X work?" for short concept names.
  if (lower.split(" ").length <= 4) {
    return `How does ${lower} work?`;
  }
  // Fallback: title case, append a question mark only if the topic field already reads as one.
  if (task.topic && task.topic.trim().endsWith("?")) return task.topic.trim();
  return titleCase(lower);
}
function titleCase(s: string): string {
  return s
    .split(" ")
    .map((w) => (w.length > 0 ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
function capitalize(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1) : s;
}

// First-sentence summary for the rubric description toggle.
function firstSentence(text: string): string {
  const s = text.trim();
  // Find the first ". " or "? " or "! " that's not inside an abbreviation.
  const m = s.match(/^.*?[.?!](?=\s|$)/);
  if (m) return m[0];
  return s.length > 140 ? s.slice(0, 140) + "…" : s;
}

export default function Page() {
  const [view, setView] = useState<View>("results");

  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [breakdown, setBreakdown] = useState<JudgeBreakdown | null>(null);
  const [activeRubric, setActiveRubric] = useState<RubricCriterion[] | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  // Models for the active run/rollout (for the "Teacher: X" labels).
  const [activeTeacher, setActiveTeacher] = useState<string | null>(null);
  const [activeJudge, setActiveJudge] = useState<string | null>(null);

  // Model picker for fresh rollouts.
  const [pickedTeacher, setPickedTeacher] = useState<string>("gpt-5.4-nano");

  // Left/right split (% width of left pane), draggable.
  const [leftPct, setLeftPct] = useState<number>(40);
  const draggingRef = useRef(false);

  const knownRunIdsBeforeRun = useRef<Set<string>>(new Set());

  // Initial load.
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

  useEffect(() => {
    if (mode === "viewing-saved") return;
    setActiveRubric(selectedTask?.rubric ?? null);
  }, [selectedTask, mode]);

  // Polling fallback (see AGENTS.md — do not remove).
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
        if (newRun) await loadSavedRun(newRun.id);
      } catch {
        /* ignore */
      }
    };
    const interval = setInterval(tick, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Draggable splitter.
  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!draggingRef.current) return;
      const pct = (e.clientX / window.innerWidth) * 100;
      setLeftPct(Math.max(20, Math.min(70, pct)));
    }
    function onUp() {
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

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
      // teacher model is encoded in the run id's last __ segment.
      const runSummary = runs.find((r) => r.id === runId);
      setActiveTeacher(runSummary?.model ?? null);
      setActiveJudge(DEFAULT_JUDGE_DISPLAY);
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
    setActiveTeacher(pickedTeacher);
    setActiveJudge(DEFAULT_JUDGE_DISPLAY);
    knownRunIdsBeforeRun.current = new Set(runs.map((r) => r.id));

    try {
      for await (const evt of streamRun({ task_id: selectedTaskId, tutor_model: pickedTeacher })) {
        if (evt.type === "info") {
          const s = (evt as { status?: string }).status ?? "";
          if (s === "starting") setStatus("Starting…");
          else if (s === "running") setStatus("Running rollout (this can take 15–60s)…");
          else if (s) setStatus(s);
        } else if (evt.type === "message") {
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
      setError(`Streaming failed (will retry via polling): ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return (
    <main className="h-screen flex flex-col">
      <header className="border-b border-[var(--color-border)] px-6 py-3 flex items-center gap-6">
        <h1 className="text-3xl font-bold tracking-tight">TeachingBench</h1>
        <span className="text-sm text-[var(--color-text-dim)]">Agent teaching eval</span>
        <nav className="ml-auto flex items-center gap-2">
          <ViewTab name="Inspect Run" active={view === "inspect"} onClick={() => setView("inspect")} />
          <ViewTab name="Results" active={view === "results"} onClick={() => setView("results")} />
          <ViewTab name="v0.1 Full Report" active={view === "report"} onClick={() => setView("report")} />
        </nav>
      </header>

      {error && (
        <div className="bg-red-900/30 border-b border-red-700 px-6 py-2 text-sm">
          <strong>Error:</strong> {error}
        </div>
      )}

      {view === "inspect" && (
        <div className="flex-1 flex min-h-0">
          <aside
            className="border-r border-[var(--color-border)] flex flex-col min-h-0"
            style={{ width: `${leftPct}%` }}
          >
            <Section title="Task">
              <select
                className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-3 py-2 text-base"
                value={selectedTaskId ?? ""}
                onChange={(e) => {
                  setSelectedTaskId(e.target.value);
                  setMode("idle");
                  setStatus("");
                  setMessages([]);
                  setBreakdown(null);
                  setSelectedRunId(null);
                  setActiveTeacher(null);
                  setActiveJudge(null);
                }}
              >
                {tasks.map((t) => (
                  <option key={t.task_id} value={t.task_id}>
                    {prettyTaskName(t)}
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
                  {activeTeacher && (
                    <span>
                      teacher: <strong className="text-[var(--color-text)]">{displayModel(activeTeacher)}</strong>
                    </span>
                  )}
                </div>
              )}
              {selectedTask && (
                <div className="mt-3">
                  <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                    Student Question
                  </div>
                  <pre className="text-sm whitespace-pre-wrap bg-[var(--color-panel)] border border-[var(--color-border)] rounded p-2.5 leading-relaxed">{selectedTask.seed_question}</pre>
                </div>
              )}
              <div className="mt-4 flex items-center gap-2">
                <select
                  className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-2 text-sm"
                  value={pickedTeacher}
                  onChange={(e) => setPickedTeacher(e.target.value)}
                  disabled={mode === "running"}
                  title="Teacher model"
                >
                  {TEACHER_MODELS.map((m) => (
                    <option key={m.id} value={m.id}>{m.display}</option>
                  ))}
                </select>
                <button
                  onClick={runFresh}
                  disabled={!selectedTaskId || mode === "running"}
                  className="flex-1 bg-[var(--color-accent)] text-black font-semibold py-2 rounded disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90"
                >
                  {mode === "running" ? "Running…" : "Run new rollout"}
                </button>
              </div>
            </Section>

            <Section title="Rubric" scroll growMore>
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

          <div
            onMouseDown={(e) => {
              draggingRef.current = true;
              e.preventDefault();
              document.body.style.cursor = "col-resize";
              document.body.style.userSelect = "none";
            }}
            className="w-1 cursor-col-resize bg-[var(--color-border)] hover:bg-[var(--color-accent)] transition-colors"
            title="Drag to resize"
          />

          <section className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <ChatView messages={messages} mode={mode} status={status} />
            </div>
            <div className="border-t border-[var(--color-border)] px-6 py-3 max-h-[40vh] overflow-y-auto">
              <ScorePanel
                breakdown={breakdown}
                teacher={activeTeacher}
                judge={activeJudge}
              />
            </div>
          </section>
        </div>
      )}

      {view === "results" && <ResultsView runs={runs} />}
      {view === "report" && <ReportView />}
    </main>
  );
}

function ViewTab({ name, active, onClick }: { name: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded text-sm font-medium border ${
        active
          ? "border-[var(--color-accent)] bg-[var(--color-panel-hover)] text-[var(--color-text)]"
          : "border-transparent text-[var(--color-text-dim)] hover:bg-[var(--color-panel-hover)]"
      }`}
    >
      {name}
    </button>
  );
}

function Section({
  title,
  children,
  scroll,
  growMore,
}: {
  title: string;
  children: React.ReactNode;
  scroll?: boolean;
  growMore?: boolean;
}) {
  return (
    <div
      className={`border-b border-[var(--color-border)] px-6 py-4 ${
        scroll ? "min-h-0 overflow-y-auto" : ""
      } ${scroll && growMore ? "flex-[2_1_0]" : scroll ? "flex-[1_1_0]" : ""}`}
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
        return <RubricCard key={c.id} criterion={c} scored={scored} score={score} />;
      })}
    </div>
  );
}

function RubricCard({
  criterion: c,
  scored,
  score,
}: {
  criterion: RubricCriterion;
  scored: boolean;
  score: number | null | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const full = c.description ?? "";
  const short = firstSentence(full);
  const hasMore = full.length > short.length;
  return (
    <article className="border border-[var(--color-border)] bg-[var(--color-panel)] rounded-md p-3">
      <header className="flex items-baseline gap-2 mb-1.5">
        <h3 className="font-semibold text-[var(--color-text)]">{prettyCriterionId(c.id)}</h3>
        {scored && <ScoreBadge value={score === undefined ? null : score} />}
      </header>
      <div className="text-xs text-[var(--color-text-dim)] leading-relaxed mb-2">
        <div className="md-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {expanded ? full : short}
          </ReactMarkdown>
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 text-[var(--color-accent)] hover:underline text-xs"
          >
            {expanded ? "show less" : "show more"}
          </button>
        )}
      </div>
      {c.anchors?.length ? <AnchorList anchors={c.anchors} /> : null}
    </article>
  );
}

function AnchorList({ anchors }: { anchors: { score: number | null; meaning: string }[] }) {
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
  if (score === null) return "rgba(138, 146, 158, 0.06)";
  if (score >= 0.75) return "rgba(90, 213, 138, 0.10)";
  if (score >= 0.4) return "rgba(243, 201, 105, 0.10)";
  return "rgba(229, 115, 115, 0.10)";
}

function anchorScoreText(score: number | null): string {
  if (score === null) return "var(--color-text-dim)";
  if (score >= 0.75) return "var(--color-good)";
  if (score >= 0.4) return "var(--color-warn)";
  return "var(--color-bad)";
}

// --- Score badge -----------------------------------------------------------

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
        No saved runs yet. Run new to create one.
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
                <span className="text-[var(--color-text-dim)]">— Teacher: {displayModel(r.model)}</span>
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
          "Pick a saved run or run new to see the transcript here."
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
    assistant: "Teacher",
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

function ScorePanel({
  breakdown,
  teacher,
  judge,
}: {
  breakdown: JudgeBreakdown | null;
  teacher: string | null;
  judge: string | null;
}) {
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
      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-xs uppercase tracking-wider text-[var(--color-text-dim)]">
          score@1
        </span>
        {composite !== undefined && composite !== null ? (
          <ScoreBadge value={composite} />
        ) : (
          <span className="text-[var(--color-text-dim)]">—</span>
        )}
        {teacher && (
          <span className="text-sm text-[var(--color-text-dim)]">
            Teacher: <span className="text-[var(--color-text)]">{displayModel(teacher)}</span>
          </span>
        )}
        {judge && (
          <span className="text-sm text-[var(--color-text-dim)]">
            Judge: <span className="text-[var(--color-text)]">{judge}</span>
          </span>
        )}
      </div>
      <div className="flex gap-3 flex-wrap">
        {Object.entries(breakdown.scores).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5 text-sm">
            <span className="text-[var(--color-text-dim)]">{prettyCriterionId(k)}</span>
            <ScoreBadge value={v as number | null} />
          </div>
        ))}
      </div>
      {breakdown.rationale && (
        <div className="text-sm mt-2">
          <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
            Judge Rationale {judge && <span className="normal-case tracking-normal">({judge})</span>}
          </div>
          <div className="text-[var(--color-text-dim)]">
            <Markdown content={breakdown.rationale} />
          </div>
        </div>
      )}
    </div>
  );
}

// --- Results view (two bar charts with tabs) ------------------------------

const CRITERION_ORDER = [
  "Overall",
  "answers_the_question",
  "factual_correctness",
  "anti_firehose",
  "meeting_student_level",
  "clarity",
  "bridging",
  "scaffolding",
  "no_excessive_validation",
];

// Distinct color per criterion (used in the per-criterion chart's single-model view).
const CRITERION_COLOR: Record<string, string> = {
  "Overall":                "#94a3b8",
  "answers_the_question":   "#ef4444",
  "factual_correctness":    "#f97316",
  "anti_firehose":          "#eab308",
  "meeting_student_level":  "#84cc16",
  "clarity":                "#06b6d4",
  "bridging":               "#3b82f6",
  "scaffolding":            "#8b5cf6",
  "no_excessive_validation":"#ec4899",
};

type Bucket = { sum: number; n: number; nullN: number };

function avgOf(b: Bucket | undefined): number | null {
  return b && b.n > 0 ? b.sum / b.n : null;
}

function ResultsView({ runs }: { runs: RunSummary[] }) {
  const [criterion, setCriterion] = useState<string>("Overall");
  const [chart2Model, setChart2Model] = useState<string>("All Models");

  // Criteria present in the data (deterministic order).
  const presentCriteria = new Set<string>();
  for (const r of runs) {
    if (r.scores) for (const k of Object.keys(r.scores)) presentCriteria.add(k);
  }
  const criteria = CRITERION_ORDER.filter((k) => k === "Overall" || presentCriteria.has(k));

  // Aggregate per (model, criterion). criterion="Overall" uses r.composite.
  const cell: Record<string, Record<string, Bucket>> = {};
  function get(m: string, c: string): Bucket {
    cell[m] ??= {};
    return (cell[m][c] ??= { sum: 0, n: 0, nullN: 0 });
  }
  for (const r of runs) {
    const m = r.model;
    // Overall
    {
      const b = get(m, "Overall");
      const v = r.composite;
      if (v === null) b.nullN += 1;
      else if (typeof v === "number") {
        b.sum += v;
        b.n += 1;
      }
    }
    // Per criterion
    if (r.scores) {
      for (const [k, v] of Object.entries(r.scores)) {
        const b = get(m, k);
        if (v === null) b.nullN += 1;
        else if (typeof v === "number") {
          b.sum += v;
          b.n += 1;
        }
      }
    }
  }

  // Stable model order: TEACHER_MODELS list, then any extras alphabetically.
  const knownIds = TEACHER_MODELS.map((m) => m.id);
  const extras = Object.keys(cell).filter((m) => !knownIds.includes(m)).sort();
  const models = [...knownIds, ...extras].filter((m) => cell[m]);

  // === Chart 1: per-model bars for one criterion ===
  const chart1Data = models.map((m) => ({
    id: m,
    display: displayModel(m),
    color: MODEL_COLOR[m] ?? "#9aa0a6",
    value: avgOf(cell[m]?.[criterion]),
    n: cell[m]?.[criterion]?.n ?? 0,
    nullN: cell[m]?.[criterion]?.nullN ?? 0,
  }));

  // === Chart 2: per-criterion bars for one (or all) model ===
  const chart2Tabs = ["All Models", ...models.map((m) => displayModel(m))];
  const totalRuns = runs.length;

  return (
    <div className="flex-1 flex flex-col min-h-0 px-8 py-6 overflow-y-auto">
      <div>
        <h2 className="text-xl font-semibold mb-1">
          Results across {totalRuns} rollouts
        </h2>
        <p className="text-sm text-[var(--color-text-dim)]">
          mean@1 — per-rollout judge score, averaged. (One rollout per task per model.)
        </p>
      </div>

      {totalRuns === 0 ? (
        <p className="mt-6 text-[var(--color-text-dim)]">
          Loading saved rollouts… If this stays empty, the backend has no rollouts.
        </p>
      ) : (
        <>
          {/* Chart 1: mean@1 by model, criterion picker */}
          <section className="mt-6">
            <div className="flex items-baseline justify-between gap-4 flex-wrap mb-2">
              <h3 className="text-base font-semibold">
                mean@1 by model · <span className="text-[var(--color-text-dim)] font-normal">{criterion === "Overall" ? "Overall" : prettyCriterionId(criterion)}</span>
              </h3>
            </div>
            <CriterionTabs
              tabs={criteria}
              active={criterion}
              onSelect={setCriterion}
              renderLabel={(t) => (t === "Overall" ? "Overall" : prettyCriterionId(t))}
            />
            <div className="mt-4">
              <SingleBarChart
                bars={chart1Data.map((d) => ({
                  id: d.id,
                  label: d.display,
                  sublabel: `n = ${d.n}${d.nullN ? `  (${d.nullN} n/a)` : ""}`,
                  value: d.value,
                  color: d.color,
                }))}
                yLabel="mean@1"
              />
            </div>
          </section>

          {/* Chart 2: mean@1 by criterion, model picker */}
          <section className="mt-10">
            <div className="flex items-baseline justify-between gap-4 flex-wrap mb-2">
              <h3 className="text-base font-semibold">
                mean@1 by criterion · <span className="text-[var(--color-text-dim)] font-normal">{chart2Model}</span>
              </h3>
            </div>
            <CriterionTabs
              tabs={chart2Tabs}
              active={chart2Model}
              onSelect={setChart2Model}
              renderLabel={(t) => t}
            />
            <div className="mt-4">
              {chart2Model === "All Models" ? (
                <GroupedBarChart
                  groups={criteria.map((c) => ({
                    label: c === "Overall" ? "Overall" : prettyCriterionId(c),
                    bars: models.map((m) => ({
                      id: m,
                      label: displayModel(m),
                      value: avgOf(cell[m]?.[c]),
                      color: MODEL_COLOR[m] ?? "#9aa0a6",
                    })),
                  }))}
                  legend={models.map((m) => ({ label: displayModel(m), color: MODEL_COLOR[m] ?? "#9aa0a6" }))}
                  yLabel="mean@1"
                />
              ) : (
                (() => {
                  const m = models.find((x) => displayModel(x) === chart2Model)!;
                  return (
                    <SingleBarChart
                      bars={criteria.map((c) => ({
                        id: c,
                        label: c === "Overall" ? "Overall" : prettyCriterionId(c),
                        sublabel: (() => {
                          const b = cell[m]?.[c];
                          return b ? `n = ${b.n}${b.nullN ? `  (${b.nullN} n/a)` : ""}` : "";
                        })(),
                        value: avgOf(cell[m]?.[c]),
                        color: CRITERION_COLOR[c] ?? "#9aa0a6",
                      }))}
                      yLabel="mean@1"
                      tilt
                    />
                  );
                })()
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function CriterionTabs({
  tabs,
  active,
  onSelect,
  renderLabel,
}: {
  tabs: string[];
  active: string;
  onSelect: (t: string) => void;
  renderLabel: (t: string) => string;
}) {
  return (
    <div className="flex gap-1 flex-wrap border-b border-[var(--color-border)]">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onSelect(t)}
          className={`px-3 py-2 text-sm border-b-2 -mb-px ${
            active === t
              ? "border-[var(--color-accent)] text-[var(--color-text)] font-medium"
              : "border-transparent text-[var(--color-text-dim)] hover:text-[var(--color-text)]"
          }`}
        >
          {renderLabel(t)}
        </button>
      ))}
    </div>
  );
}

// Rounded-top rect built as an SVG path (flat bottom, rounded top corners).
function topRoundedPath(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return `M ${x} ${y + h} L ${x} ${y + rr} Q ${x} ${y} ${x + rr} ${y} L ${x + w - rr} ${y} Q ${x + w} ${y} ${x + w} ${y + rr} L ${x + w} ${y + h} Z`;
}

function SingleBarChart({
  bars,
  yLabel,
  tilt,
}: {
  bars: { id: string; label: string; sublabel?: string; value: number | null; color: string }[];
  yLabel: string;
  tilt?: boolean;
}) {
  if (!bars.length) {
    return <p className="text-sm text-[var(--color-text-dim)]">No data.</p>;
  }
  const W = 820;
  const H = tilt ? 400 : 360;
  const padL = 56;
  const padR = 24;
  const padT = 16;
  const padB = tilt ? 110 : 72;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const barGap = Math.max(12, Math.floor(innerW / (bars.length * 4)));
  const barW = (innerW - barGap * (bars.length - 1)) / bars.length;
  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <div className="max-w-4xl">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {yTicks.map((t) => {
          const y = padT + innerH - innerH * t;
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--color-border)" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="12" fill="var(--color-text-dim)">
                {t.toFixed(2)}
              </text>
            </g>
          );
        })}
        <text
          x={14}
          y={padT + innerH / 2}
          fontSize="12"
          fill="var(--color-text-dim)"
          transform={`rotate(-90 14 ${padT + innerH / 2})`}
          textAnchor="middle"
        >
          {yLabel}
        </text>
        {bars.map((d, i) => {
          const x = padL + i * (barW + barGap);
          const h = d.value !== null ? innerH * d.value : 0;
          const y = padT + innerH - h;
          return (
            <g key={d.id}>
              {d.value !== null ? (
                <>
                  <path d={topRoundedPath(x, y, barW, h, 4)} fill={d.color} />
                  <text x={x + barW / 2} y={y - 6} textAnchor="middle" fontSize="13" fill="var(--color-text)" fontWeight={600}>
                    {d.value.toFixed(2)}
                  </text>
                </>
              ) : (
                <text x={x + barW / 2} y={padT + innerH - 6} textAnchor="middle" fontSize="12" fill="var(--color-text-dim)">
                  n/a
                </text>
              )}
              {tilt ? (
                <text
                  x={x + barW / 2}
                  y={padT + innerH + 14}
                  textAnchor="end"
                  fontSize="12"
                  fill="var(--color-text)"
                  transform={`rotate(-30 ${x + barW / 2} ${padT + innerH + 14})`}
                >
                  {d.label}
                </text>
              ) : (
                <>
                  <text
                    x={x + barW / 2}
                    y={padT + innerH + 22}
                    textAnchor="middle"
                    fontSize="13"
                    fill="var(--color-text)"
                  >
                    {d.label}
                  </text>
                  {d.sublabel ? (
                    <text
                      x={x + barW / 2}
                      y={padT + innerH + 40}
                      textAnchor="middle"
                      fontSize="11"
                      fill="var(--color-text-dim)"
                    >
                      {d.sublabel}
                    </text>
                  ) : null}
                </>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function GroupedBarChart({
  groups,
  legend,
  yLabel,
}: {
  groups: { label: string; bars: { id: string; label: string; value: number | null; color: string }[] }[];
  legend: { label: string; color: string }[];
  yLabel: string;
}) {
  if (!groups.length) {
    return <p className="text-sm text-[var(--color-text-dim)]">No data.</p>;
  }
  const W = 900;
  const H = 420;
  const padL = 56;
  const padR = 24;
  const padT = 16;
  const padB = 110;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const barsPerGroup = groups[0].bars.length;
  const groupGap = 22;
  const innerBarGap = 3;
  const groupW = (innerW - groupGap * (groups.length - 1)) / groups.length;
  const barW = (groupW - innerBarGap * (barsPerGroup - 1)) / barsPerGroup;
  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  return (
    <div className="max-w-5xl">
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs mb-2 text-[var(--color-text-dim)]">
        {legend.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-1.5">
            <span style={{ background: l.color, width: 10, height: 10, borderRadius: 2, display: "inline-block" }} />
            {l.label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {yTicks.map((t) => {
          const y = padT + innerH - innerH * t;
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--color-border)" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="12" fill="var(--color-text-dim)">
                {t.toFixed(2)}
              </text>
            </g>
          );
        })}
        <text
          x={14}
          y={padT + innerH / 2}
          fontSize="12"
          fill="var(--color-text-dim)"
          transform={`rotate(-90 14 ${padT + innerH / 2})`}
          textAnchor="middle"
        >
          {yLabel}
        </text>
        {groups.map((g, gi) => {
          const gx = padL + gi * (groupW + groupGap);
          return (
            <g key={g.label}>
              {g.bars.map((d, bi) => {
                const x = gx + bi * (barW + innerBarGap);
                const h = d.value !== null ? innerH * d.value : 0;
                const y = padT + innerH - h;
                return d.value !== null ? (
                  <path key={d.id} d={topRoundedPath(x, y, barW, h, 3)} fill={d.color} />
                ) : null;
              })}
              <text
                x={gx + groupW / 2}
                y={padT + innerH + 14}
                textAnchor="end"
                fontSize="12"
                fill="var(--color-text)"
                transform={`rotate(-30 ${gx + groupW / 2} ${padT + innerH + 14})`}
              >
                {g.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// --- Report view -----------------------------------------------------------

function ReportView() {
  const [content, setContent] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/baseline_report.md", { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.text();
      })
      .then(setContent)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <div className="max-w-3xl mx-auto">
        {err && (
          <div className="bg-red-900/30 border border-red-700 px-4 py-2 rounded text-sm mb-4">
            Failed to load report: {err}
          </div>
        )}
        {content ? (
          <div className="md-content text-base leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : !err ? (
          <p className="text-[var(--color-text-dim)]">Loading…</p>
        ) : null}
      </div>
    </div>
  );
}
