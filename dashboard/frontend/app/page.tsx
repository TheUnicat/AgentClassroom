"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamRun } from "@/lib/api";
import type {
  JudgeBreakdown,
  Message,
  RubricCriterion,
  RunSummary,
  Task,
  TrajectoryTurn,
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

// Fallback judge display if /api/health doesn't surface one (older backend).
// The actual judge for saved rollouts isn't stored per-rollout yet; we use the
// backend's currently-configured judge as a best-effort attribution.
const DEFAULT_JUDGE_DISPLAY = "Opus 4.7";

// Hand-overrides for criterion display names. Anything not in this map falls
// back to the generic Title-Case-with-spaces formatter.
const CRITERION_DISPLAY: Record<string, string> = {
  anti_firehose:           "Anti-Firehose",
  no_excessive_validation: "Anti-Sycophancy",
};

function prettyCriterionId(id: string): string {
  if (CRITERION_DISPLAY[id]) return CRITERION_DISPLAY[id];
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

// Hand-crafted one-line briefs for the rubric. Falls back to the full description
// if a criterion id isn't here. The "show full description" toggle reveals the
// verbatim system description from the backend.
const CRITERION_BRIEF: Record<string, string> = {
  answers_the_question:    "Did the teacher actually answer what the student asked?",
  factual_correctness:     "Are the technical claims correct, and not subtly misleading?",
  bridging:                "Did the teacher use the materials or context the student shared?",
  anti_firehose:           "Did the teacher stay concise and focused, instead of info-dumping?",
  meeting_student_level:   "Did the teacher pitch the explanation at the student's actual level?",
  scaffolding:             "Did the teacher build up step by step, instead of jumping ahead?",
  clarity:                 "Is the writing clear and logically organized?",
  no_excessive_validation: "Did the teacher avoid sycophantic praise (\"great question!\")?",
};

export default function Page() {
  const [view, setView] = useState<View>("results");

  const [tasks, setTasks] = useState<Task[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [breakdown, setBreakdown] = useState<JudgeBreakdown | null>(null);
  const [trajectory, setTrajectory] = useState<TrajectoryTurn[] | null>(null);
  const [tutorPromptName, setTutorPromptName] = useState<string>("default");
  const [tutorPromptText, setTutorPromptText] = useState<string>("");
  const [activeRubric, setActiveRubric] = useState<RubricCriterion[] | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  // Models for the active run/rollout (for the "Teacher: X" labels).
  const [activeTeacher, setActiveTeacher] = useState<string | null>(null);
  const [activeJudge, setActiveJudge] = useState<string | null>(null);

  // Model picker for fresh rollouts.
  const [pickedTeacher, setPickedTeacher] = useState<string>("gpt-5.4-nano");

  // Configured judge model (from /api/health). Falls back to DEFAULT_JUDGE_DISPLAY.
  const [judgeDisplay, setJudgeDisplay] = useState<string>(DEFAULT_JUDGE_DISPLAY);

  // Saved-runs filters (Demo sidebar). Persisted across view switches so a
  // click-to-drill from the Results page can prefilter to one model.
  const [filterModel, setFilterModel] = useState<string | null>(null);
  const [filterScoreBand, setFilterScoreBand] = useState<"high" | "mid" | "low" | null>(null);
  const [filterQuery, setFilterQuery] = useState<string>("");

  // Left/right split (% width of left pane), draggable.
  const [leftPct, setLeftPct] = useState<number>(40);
  const draggingRef = useRef(false);

  const knownRunIdsBeforeRun = useRef<Set<string>>(new Set());

  // Initial load.
  useEffect(() => {
    (async () => {
      try {
        const [t, r, h] = await Promise.all([
          api.listTasks(),
          api.listRuns(),
          api.health().catch(() => null),
        ]);
        setTasks(t);
        setRuns(r);
        if (t.length && !selectedTaskId) setSelectedTaskId(t[0].task_id);
        if (h?.default_judge_model) setJudgeDisplay(displayModel(h.default_judge_model));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply current filters to the saved-runs list.
  const filteredRuns = runs.filter((r) => {
    if (filterModel && r.model !== filterModel) return false;
    if (filterScoreBand) {
      const s = r.composite;
      if (s === null || s === undefined) return false;
      if (filterScoreBand === "high" && s < 0.75) return false;
      if (filterScoreBand === "mid" && (s < 0.4 || s >= 0.75)) return false;
      if (filterScoreBand === "low" && s >= 0.4) return false;
    }
    if (filterQuery) {
      const q = filterQuery.toLowerCase();
      if (!(r.task_id ?? "").toLowerCase().includes(q)) return false;
    }
    return true;
  });

  // Used by chart bars (specific model) AND the "go to Demo" link (modelId = "").
  // Empty model → no filter, just switch views.
  function drillToModel(modelId: string) {
    setFilterModel(modelId || null);
    setFilterScoreBand(null);
    setFilterQuery("");
    setView("inspect");
  }

  const selectedTask = tasks.find((t) => t.task_id === selectedTaskId) ?? null;

  useEffect(() => {
    if (mode === "viewing-saved") return;
    setActiveRubric(selectedTask?.rubric ?? null);
  }, [selectedTask, mode]);

  // Auto-load a matching saved rollout when the user picks (or initially lands on)
  // a task — so the right pane isn't empty until they hit "Run new rollout."
  // Prefer a run matching the picked teacher; otherwise fall back to newest for the task.
  useEffect(() => {
    if (!selectedTaskId || !runs.length) return;
    if (mode === "running" || mode === "done") return; // don't disturb a fresh rollout
    const candidates = runs.filter((r) => r.task_id === selectedTaskId);
    if (!candidates.length) {
      // No saved rollout for this task — clear stale right-pane content.
      setMessages([]);
      setBreakdown(null);
      setTrajectory(null);
      setTutorPromptName("default");
      setTutorPromptText("");
      setSelectedRunId(null);
      setActiveTeacher(null);
      setActiveJudge(null);
      return;
    }
    const byTeacher = candidates.find((r) => r.model === pickedTeacher);
    const pick = byTeacher ?? candidates[0]; // backend returns newest-first
    if (pick.id !== selectedRunId) loadSavedRun(pick.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTaskId, runs.length]);

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
    setTrajectory(null);
    setTutorPromptName("default");
    setTutorPromptText("");
    try {
      const detail = await api.getRun(runId);
      setMessages(detail.messages);
      setBreakdown(detail.judge_breakdown);
      setTrajectory(detail.trajectory ?? null);
      setTutorPromptName(detail.tutor_system_prompt_name ?? "default");
      setTutorPromptText(detail.tutor_system_prompt ?? "");
      setActiveRubric(detail.rubric ?? selectedTask?.rubric ?? null);
      if (detail.task_id) setSelectedTaskId(detail.task_id);
      // teacher model is encoded in the run id's last __ segment.
      const runSummary = runs.find((r) => r.id === runId);
      setActiveTeacher(runSummary?.model ?? null);
      setActiveJudge(judgeDisplay);
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
    setTrajectory(null);
    setTutorPromptName("default");
    setTutorPromptText("");
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
        <h1 className="text-3xl font-bold tracking-tight">AgentClassroom</h1>
        <nav className="ml-auto flex items-center gap-1.5">
          <ViewTab name="Results" active={view === "results"} onClick={() => setView("results")} />
          <ViewTab name="Demo" active={view === "inspect"} onClick={() => setView("inspect")} />
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
            <Section title={`Saved runs (${filteredRuns.length}${filteredRuns.length !== runs.length ? ` of ${runs.length}` : ""})`} scroll>
              <RunsFilters
                runs={runs}
                model={filterModel}
                onModelChange={setFilterModel}
                scoreBand={filterScoreBand}
                onScoreBandChange={setFilterScoreBand}
                query={filterQuery}
                onQueryChange={setFilterQuery}
              />
              <RunsList
                runs={filteredRuns}
                selectedRunId={selectedRunId}
                onSelect={loadSavedRun}
              />
            </Section>

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
                <div className="mt-3 text-sm text-[var(--color-text)] flex gap-x-4 gap-y-1 flex-wrap">
                  <span>
                    <span className="text-[var(--color-text-dim)]">subject:</span>{" "}
                    <strong>{selectedTask.subject}</strong>
                  </span>
                  <span>
                    <span className="text-[var(--color-text-dim)]">turns:</span>{" "}
                    <strong>{selectedTask.turns}</strong>
                  </span>
                  <span>
                    <span className="text-[var(--color-text-dim)]">difficulty:</span>{" "}
                    <strong>{selectedTask.difficulty}</strong>
                  </span>
                  <span>
                    <span className="text-[var(--color-text-dim)]">materials:</span>{" "}
                    <strong>{selectedTask.has_materials ? "yes" : "none"}</strong>
                  </span>
                  {activeTeacher && (
                    <span>
                      <span className="text-[var(--color-text-dim)]">teacher:</span>{" "}
                      <strong>{displayModel(activeTeacher)}</strong>
                    </span>
                  )}
                </div>
              )}
              {selectedTask && (
                <div className="mt-3">
                  <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
                    Student Question
                  </div>
                  <div className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded p-2.5">
                    <Markdown content={selectedTask.seed_question} />
                  </div>
                </div>
              )}
              <div className="mt-4 flex items-center gap-2 flex-wrap">
                <label className="flex items-center gap-1.5 text-sm text-[var(--color-text-dim)]">
                  Teacher:
                  <select
                    className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2 py-2 text-sm text-[var(--color-text)]"
                    value={pickedTeacher}
                    onChange={(e) => setPickedTeacher(e.target.value)}
                    disabled={mode === "running"}
                  >
                    {TEACHER_MODELS.map((m) => (
                      <option key={m.id} value={m.id}>{m.display}</option>
                    ))}
                  </select>
                </label>
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
            {mode === "viewing-saved" && selectedRunId && (
              <div className="border-b border-[var(--color-border)] px-6 py-2 text-xs text-[var(--color-text-dim)] flex items-center gap-2 bg-[var(--color-panel)]">
                <span>📂 Showing saved rollout</span>
                <span className="font-mono">{runs.find((r) => r.id === selectedRunId)?.timestamp ?? ""}</span>
                <span className="text-[var(--color-text)]">— click <strong>Run new rollout</strong> to generate a fresh one.</span>
              </div>
            )}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              <TeacherPromptPanel name={tutorPromptName} text={tutorPromptText} />
              <ChatView messages={messages} mode={mode} status={status} trajectory={trajectory} />
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

      {view === "results" && <ResultsView runs={runs} onDrillToModel={drillToModel} />}
      {view === "report" && <ReportView />}
    </main>
  );
}

function ViewTab({ name, active, onClick }: { name: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-md text-base font-semibold transition-colors ${
        active
          ? "bg-[var(--color-accent)] text-black"
          : "text-[var(--color-text-dim)] hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
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
  const full = (c.description ?? "").trim();
  const brief = CRITERION_BRIEF[c.id] ?? full;
  // If we don't have a hand-crafted brief and the description is short, there's
  // nothing to expand to — only show the toggle when expanding actually adds info.
  const hasMore = brief !== full && full.length > 0;
  return (
    <article className="border border-[var(--color-border)] bg-[var(--color-panel)] rounded-md p-3">
      <header className="flex items-baseline gap-2 mb-1.5">
        <h3 className="font-semibold text-[var(--color-text)]">{prettyCriterionId(c.id)}</h3>
        {scored && <ScoreBadge value={score === undefined ? null : score} />}
      </header>
      <div className="text-xs text-[var(--color-text-dim)] leading-relaxed mb-2">
        {expanded ? (
          <div className="md-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{full}</ReactMarkdown>
          </div>
        ) : (
          <p>{brief}</p>
        )}
        {hasMore && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1 text-[var(--color-accent)] hover:underline text-xs"
          >
            {expanded ? "hide full description" : "show full description"}
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

function ScoreBadge({
  value,
  prominent,
}: {
  value: number | null;
  prominent?: boolean;
}) {
  const sizing = prominent
    ? "text-2xl px-3.5 py-1.5 font-bold"
    : "text-xs px-2 py-0.5";
  if (value === null) {
    // Greyer styling than the colored bands, so N/A reads as "skipped" not "low score".
    return (
      <span
        className={`rounded font-mono ${sizing}`}
        style={{
          background: "rgba(138, 146, 158, 0.18)",
          color: "var(--color-text-dim)",
        }}
      >
        N/A
      </span>
    );
  }
  const color =
    value >= 0.75 ? "var(--color-good)" : value >= 0.4 ? "var(--color-warn)" : "var(--color-bad)";
  return (
    <span className={`rounded font-mono ${sizing}`} style={{ backgroundColor: color, color: "#000" }}>
      {value.toFixed(2)}
    </span>
  );
}

// --- Saved runs list -------------------------------------------------------

// Sort dropdown + filter chips above the runs list. Chips read state from the parent.
function RunsFilters({
  runs,
  model,
  onModelChange,
  scoreBand,
  onScoreBandChange,
  query,
  onQueryChange,
}: {
  runs: RunSummary[];
  model: string | null;
  onModelChange: (m: string | null) => void;
  scoreBand: "high" | "mid" | "low" | null;
  onScoreBandChange: (b: "high" | "mid" | "low" | null) => void;
  query: string;
  onQueryChange: (q: string) => void;
}) {
  // Model chip set = whatever models actually appear in the data, in TEACHER_MODELS order.
  const presentModels = new Set(runs.map((r) => r.model));
  const orderedModels = [
    ...TEACHER_MODELS.map((m) => m.id),
    ...Array.from(presentModels).filter((m) => !TEACHER_MODELS.some((tm) => tm.id === m)).sort(),
  ].filter((m) => presentModels.has(m));

  function Chip({
    active,
    onClick,
    children,
    color,
  }: {
    active: boolean;
    onClick: () => void;
    children: React.ReactNode;
    color?: string;
  }) {
    return (
      <button
        onClick={onClick}
        className={`text-xs px-2 py-1 rounded border transition-colors ${
          active
            ? "bg-[var(--color-accent)] border-[var(--color-accent)] text-black font-medium"
            : "border-[var(--color-border)] text-[var(--color-text-dim)] hover:bg-[var(--color-panel-hover)] hover:text-[var(--color-text)]"
        }`}
        style={active && color ? { background: color, borderColor: color } : undefined}
      >
        {children}
      </button>
    );
  }

  return (
    <div className="space-y-2 mb-3">
      <input
        type="text"
        placeholder="Search task…"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        className="w-full bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-2.5 py-1.5 text-sm placeholder:text-[var(--color-text-dim)] focus:outline-none focus:border-[var(--color-accent)]"
      />
      <div className="flex flex-wrap gap-1">
        <Chip active={!model} onClick={() => onModelChange(null)}>
          All teachers
        </Chip>
        {orderedModels.map((m) => (
          <Chip
            key={m}
            active={model === m}
            onClick={() => onModelChange(model === m ? null : m)}
            color={MODEL_COLOR[m]}
          >
            {displayModel(m)}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">
        <Chip active={!scoreBand} onClick={() => onScoreBandChange(null)}>
          Any score
        </Chip>
        <Chip active={scoreBand === "high"} onClick={() => onScoreBandChange(scoreBand === "high" ? null : "high")}>
          High (≥0.75)
        </Chip>
        <Chip active={scoreBand === "mid"} onClick={() => onScoreBandChange(scoreBand === "mid" ? null : "mid")}>
          Mid (0.4–0.75)
        </Chip>
        <Chip active={scoreBand === "low"} onClick={() => onScoreBandChange(scoreBand === "low" ? null : "low")}>
          Low (&lt;0.4)
        </Chip>
      </div>
    </div>
  );
}

type SortKey = "newest" | "score-desc" | "score-asc" | "task";

function RunsList({
  runs,
  selectedRunId,
  onSelect,
}: {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>("newest");
  const sorted = [...runs].sort((a, b) => {
    if (sort === "newest") return (b.timestamp ?? "").localeCompare(a.timestamp ?? "");
    if (sort === "task") return (a.task_id ?? "").localeCompare(b.task_id ?? "");
    const av = a.composite ?? -Infinity;
    const bv = b.composite ?? -Infinity;
    return sort === "score-desc" ? bv - av : av - bv;
  });
  if (!sorted.length) {
    return (
      <p className="text-[var(--color-text-dim)] text-sm">
        No runs match the current filters.
      </p>
    );
  }
  return (
    <>
      <div className="flex items-center gap-2 mb-2 text-xs text-[var(--color-text-dim)]">
        <span>Sort:</span>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="bg-[var(--color-panel)] border border-[var(--color-border)] rounded px-1.5 py-0.5"
        >
          <option value="newest">Newest first</option>
          <option value="score-desc">Score, high→low</option>
          <option value="score-asc">Score, low→high</option>
          <option value="task">Task A→Z</option>
        </select>
      </div>
      <ul className="divide-y divide-[var(--color-border)] border border-[var(--color-border)] rounded overflow-hidden">
        {sorted.map((r) => {
          const active = r.id === selectedRunId;
          // Compact, table-like row: score badge / task (truncated) / teacher.
          return (
            <li key={r.id}>
              <button
                onClick={() => onSelect(r.id)}
                className={`grid grid-cols-[48px_1fr_auto] items-center gap-2 px-2 py-1.5 text-xs w-full text-left ${
                  active
                    ? "bg-[var(--color-panel-hover)] border-l-2 border-[var(--color-accent)]"
                    : "hover:bg-[var(--color-panel-hover)] border-l-2 border-transparent"
                }`}
              >
                <ScoreBadge value={r.composite} />
                <span className="truncate text-[var(--color-text)]" title={r.task_id ?? ""}>
                  {r.task_id ?? "?"}
                </span>
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium"
                  style={{ background: (MODEL_COLOR[r.model] ?? "#9aa0a6") + "33", color: MODEL_COLOR[r.model] ?? "#9aa0a6" }}
                >
                  {displayModel(r.model)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

// --- Chat ------------------------------------------------------------------

function ChatView({
  messages,
  mode,
  status,
  trajectory,
}: {
  messages: Message[];
  mode: Mode;
  status: string;
  trajectory: TrajectoryTurn[] | null;
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
  // Map message index → trajectory entry for that assistant turn, if any.
  const trajByMsgIdx = new Map<number, TrajectoryTurn>();
  (trajectory ?? []).forEach((t) => trajByMsgIdx.set(t.msg_idx, t));
  return (
    <div className="space-y-3">
      {messages.map((m, i) => (
        <MessageBubble key={i} message={m} turn={trajByMsgIdx.get(i)} />
      ))}
      {mode === "running" && (
        <div className="text-xs text-[var(--color-text-dim)] animate-pulse">
          {status || "…"}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message, turn }: { message: Message; turn?: TrajectoryTurn }) {
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
      {role === "assistant" && turn && <TurnScorePanel turn={turn} />}
      <Markdown content={message.content} />
    </div>
  );
}

// ---- Teacher system-prompt pill + expandable markdown ------------------
// Renders at the top of the Demo right pane. Shows a conspicuous title
// chip with the prompt's registry name ("Optimized", "Socratic",
// "Default", etc.). Click to expand the full prompt as markdown.
// "Default" is unexpandable (no custom text to show).

const PROMPT_DISPLAY_NAMES: Record<string, string> = {
  default: "Default",
  custom: "Custom",
  socratic: "Socratic",
  concise: "Concise",
  materials_first: "Materials-first",
  optimized: "Optimized",
};

function prettyPromptName(name: string): string {
  return PROMPT_DISPLAY_NAMES[name] ?? name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function TeacherPromptPanel({ name, text }: { name: string; text: string }) {
  const [expanded, setExpanded] = useState(false);
  const isDefault = name === "default" || !text;
  const display = prettyPromptName(name);
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[var(--color-text-dim)]">Teacher prompt:</span>
        {isDefault ? (
          <span className="inline-flex items-center rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] px-2 py-0.5 text-[var(--color-text-dim)]">
            {display}
          </span>
        ) : (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--color-accent)] bg-[var(--color-panel)] px-2 py-0.5 text-[var(--color-accent)] hover:bg-[var(--color-panel-hover)]"
          >
            <span className="font-medium">{display}</span>
            <span className="text-[10px]">{expanded ? "▲ hide" : "▼ show full"}</span>
          </button>
        )}
      </div>
      {expanded && !isDefault && (
        <div className="mt-2 rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
            Full system prompt
          </div>
          <Markdown content={text} />
        </div>
      )}
    </div>
  );
}

// ---- Per-message state value + turn score widget ------------------------
// Renders under each AI message in the Demo view. Shows the conversation's
// state value at this turn, plus the turn score (delta from the previous
// turn). Both have hover breakdowns + (i) info tooltips.

function TurnScorePanel({ turn }: { turn: TrajectoryTurn }) {
  return (
    <div className="mt-2 flex items-center gap-3 text-xs">
      <ScoreChip
        label="State value"
        value={turn.state_value}
        signed={false}
        info="Score for the conversation up to this point. Higher is better."
        breakdown={turn.state_breakdown}
        breakdownTitle="State breakdown at this turn"
      />
      <ScoreChip
        label="Turn score"
        value={turn.turn_score}
        signed={true}
        info="How good this turn was: state value at this turn minus the previous turn's. Higher is better."
        breakdown={turn.turn_breakdown}
        breakdownTitle="Turn delta by criterion"
      />
    </div>
  );
}

function ScoreChip({
  label,
  value,
  signed,
  info,
  breakdown,
  breakdownTitle,
}: {
  label: string;
  value: number;
  signed: boolean;
  info: string;
  breakdown: Record<string, number | null>;
  breakdownTitle: string;
}) {
  const sign = signed && value > 0 ? "+" : "";
  // Color: state value cool→warm; turn score signed red/green.
  let valueColor = "var(--color-text)";
  if (signed) {
    valueColor = value > 0.001 ? "var(--color-good)" : value < -0.001 ? "var(--color-bad)" : "var(--color-text-dim)";
  }
  return (
    <div className="group relative inline-flex items-center gap-1.5 rounded-md border border-[var(--color-border)] px-2 py-1 bg-[var(--color-panel-hover)]">
      <span className="text-[var(--color-text-dim)]">{label}:</span>
      <span style={{ color: valueColor }} className="font-medium tabular-nums">
        {sign}{value.toFixed(3)}
      </span>
      <InfoCircle text={info} />
      {/* Hover breakdown panel */}
      <div className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden min-w-[260px] max-w-[360px] rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-2 shadow-lg group-hover:block">
        <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-dim)] mb-1">{breakdownTitle}</div>
        <BreakdownTable breakdown={breakdown} signed={signed} />
      </div>
    </div>
  );
}

function BreakdownTable({
  breakdown,
  signed,
}: {
  breakdown: Record<string, number | null>;
  signed: boolean;
}) {
  const entries = Object.entries(breakdown);
  return (
    <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-xs">
      {entries.map(([crit, val]) => {
        let display: string;
        let color = "var(--color-text)";
        if (val === null || val === undefined) {
          display = "—";
          color = "var(--color-text-dim)";
        } else if (signed) {
          const sgn = val > 0 ? "+" : "";
          display = `${sgn}${val.toFixed(3)}`;
          color = val > 0.001 ? "var(--color-good)" : val < -0.001 ? "var(--color-bad)" : "var(--color-text-dim)";
        } else {
          display = val.toFixed(3);
        }
        return (
          <Fragment key={crit}>
            <div className="text-[var(--color-text-dim)] truncate">{prettyCriterionId(crit)}</div>
            <div className="tabular-nums" style={{ color }}>{display}</div>
          </Fragment>
        );
      })}
    </div>
  );
}

function InfoCircle({ text }: { text: string }) {
  return (
    <span className="group/info relative inline-flex">
      <span className="inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-[var(--color-text-dim)] text-[9px] text-[var(--color-text-dim)] hover:border-[var(--color-text)] hover:text-[var(--color-text)]">
        i
      </span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1 hidden -translate-x-1/2 whitespace-normal rounded border border-[var(--color-border)] bg-[var(--color-panel)] px-2 py-1 text-[11px] leading-tight shadow-md group-hover/info:block" style={{ width: 220 }}>
        {text}
      </span>
    </span>
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
    <div className="space-y-3">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-bold uppercase tracking-wider text-[var(--color-text)]">
            Score@1
          </span>
          {composite !== undefined && composite !== null ? (
            <ScoreBadge value={composite} prominent />
          ) : (
            <span className="text-[var(--color-text-dim)]">—</span>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap text-sm">
          {teacher && (
            <span className="px-2 py-1 rounded bg-[var(--color-panel-hover)] text-[var(--color-text)]">
              <span className="text-[var(--color-text-dim)]">Teacher: </span>
              <strong>{displayModel(teacher)}</strong>
            </span>
          )}
          {judge && (
            <span className="px-2 py-1 rounded bg-[var(--color-panel-hover)] text-[var(--color-text)]">
              <span className="text-[var(--color-text-dim)]">Judge: </span>
              <strong>{judge}</strong>
            </span>
          )}
        </div>
      </div>
      <div className="flex gap-3 flex-wrap">
        {Object.entries(breakdown.scores).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5 text-sm">
            <span className="text-[var(--color-text)]">{prettyCriterionId(k)}</span>
            <ScoreBadge value={v as number | null} />
          </div>
        ))}
      </div>
      {breakdown.rationale && (
        <div className="text-sm mt-2">
          <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)] mb-1">
            Judge Rationale
          </div>
          <div className="text-[var(--color-text)]">
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

type Bucket = {
  sum: number;
  n: number;
  nullN: number;
  min: number;
  max: number;
  values: number[]; // kept for pass@τ recomputation as τ slides
};

function newBucket(): Bucket {
  return { sum: 0, n: 0, nullN: 0, min: Infinity, max: -Infinity, values: [] };
}

function addToBucket(b: Bucket, v: number | null | undefined) {
  if (v === null) {
    b.nullN += 1;
    return;
  }
  if (typeof v !== "number") return;
  b.sum += v;
  b.n += 1;
  if (v < b.min) b.min = v;
  if (v > b.max) b.max = v;
  b.values.push(v);
}

function meanOf(b: Bucket | undefined): number | null {
  return b && b.n > 0 ? b.sum / b.n : null;
}

function passAtOf(b: Bucket | undefined, tau: number): number | null {
  if (!b || b.n === 0) return null;
  let pass = 0;
  for (const v of b.values) if (v >= tau) pass += 1;
  return pass / b.n;
}

function sdOf(values: number[], mean: number): number {
  if (values.length < 2) return 0;
  const sumSq = values.reduce((s, x) => s + (x - mean) ** 2, 0);
  return Math.sqrt(sumSq / values.length);
}

// Build a hover-tooltip string with summary stats for a bar.
function statsTooltip(label: string, b: Bucket | undefined, mean: number | null): string {
  if (!b || b.n === 0) return `${label}\nno data`;
  const sd = mean !== null ? sdOf(b.values, mean) : 0;
  const range = b.max - b.min;
  return (
    `${label}\n` +
    `n = ${b.n}${b.nullN ? `  (${b.nullN} n/a)` : ""}\n` +
    `mean = ${mean !== null ? mean.toFixed(3) : "—"}\n` +
    `sd   = ${sd.toFixed(3)}\n` +
    `min  = ${b.min.toFixed(3)}\n` +
    `max  = ${b.max.toFixed(3)}\n` +
    `range = ${range.toFixed(3)}`
  );
}

type Metric = "mean@1" | "pass";

function ResultsView({
  runs,
  onDrillToModel,
}: {
  runs: RunSummary[];
  onDrillToModel: (modelId: string) => void;
}) {
  const [criterion, setCriterion] = useState<string>("Overall");
  const [chart2Model, setChart2Model] = useState<string>("All Models");
  const [metric, setMetric] = useState<Metric>("mean@1");
  const [tau, setTau] = useState<number>(0.75);

  const presentCriteria = new Set<string>();
  for (const r of runs) {
    if (r.scores) for (const k of Object.keys(r.scores)) presentCriteria.add(k);
  }
  const criteria = CRITERION_ORDER.filter((k) => k === "Overall" || presentCriteria.has(k));

  // Aggregate per (model, criterion).
  const cell: Record<string, Record<string, Bucket>> = {};
  function get(m: string, c: string): Bucket {
    cell[m] ??= {};
    return (cell[m][c] ??= newBucket());
  }
  for (const r of runs) {
    addToBucket(get(r.model, "Overall"), r.composite);
    if (r.scores) {
      for (const [k, v] of Object.entries(r.scores)) addToBucket(get(r.model, k), v);
    }
  }

  const knownIds = TEACHER_MODELS.map((m) => m.id);
  const extras = Object.keys(cell).filter((m) => !knownIds.includes(m)).sort();
  const models = [...knownIds, ...extras].filter((m) => cell[m]);

  // Metric helper: returns the displayed bar value.
  function val(b: Bucket | undefined): number | null {
    if (!b || b.n === 0) return null;
    return metric === "mean@1" ? b.sum / b.n : passAtOf(b, tau);
  }

  const yLabel = metric === "mean@1" ? "Mean@1" : `Pass@τ (τ = ${tau.toFixed(2)})`;
  const yFmt = (v: number) =>
    metric === "mean@1" ? v.toFixed(2) : `${(v * 100).toFixed(1)}%`;

  // ===== headline KPI cards =====
  // mean@1 across all rollouts; Pass@0.75 across all rollouts; best model + score; n.
  let overallMeanSum = 0;
  let overallMeanN = 0;
  let overallPass = 0;
  for (const r of runs) {
    if (typeof r.composite === "number") {
      overallMeanSum += r.composite;
      overallMeanN += 1;
      if (r.composite >= 0.75) overallPass += 1;
    }
  }
  const overallMean = overallMeanN > 0 ? overallMeanSum / overallMeanN : null;
  const overallPassRate = overallMeanN > 0 ? overallPass / overallMeanN : null;
  let bestModel: { id: string; value: number } | null = null;
  for (const m of models) {
    const v = meanOf(cell[m]?.["Overall"]);
    if (v !== null && (!bestModel || v > bestModel.value)) bestModel = { id: m, value: v };
  }

  const totalRuns = runs.length;

  return (
    <div className="flex-1 min-h-0 px-8 py-6 overflow-y-auto">
     <div className="max-w-5xl mx-auto text-center">
      <div>
        <h2 className="text-xl font-semibold mb-1">Results across {totalRuns} rollouts</h2>
        <p className="text-sm text-[var(--color-text-dim)]">
          Mean@1 = average score over all tasks. Pass@τ = % of rollouts at or above τ.
        </p>
        <p className="text-sm text-[var(--color-text-dim)] mt-1">
          Go to{" "}
          <button
            onClick={() => onDrillToModel("")}
            className="text-[var(--color-accent)] underline underline-offset-2 hover:opacity-80"
          >
            Demo
          </button>{" "}
          to inspect any of the past rollouts or run a new one.
        </p>
      </div>
      <div className="flex items-center justify-center gap-3 mt-5">
        <div className="inline-flex rounded-md border border-[var(--color-border)] overflow-hidden">
          <button
            onClick={() => setMetric("mean@1")}
            className={`px-3 py-1.5 text-sm ${
              metric === "mean@1"
                ? "bg-[var(--color-accent)] text-black font-semibold"
                : "text-[var(--color-text-dim)] hover:bg-[var(--color-panel-hover)]"
            }`}
          >
            Mean@1
          </button>
          <button
            onClick={() => setMetric("pass")}
            className={`px-3 py-1.5 text-sm border-l border-[var(--color-border)] ${
              metric === "pass"
                ? "bg-[var(--color-accent)] text-black font-semibold"
                : "text-[var(--color-text-dim)] hover:bg-[var(--color-panel-hover)]"
            }`}
          >
            Pass@τ
          </button>
        </div>
        {metric === "pass" && (
          <label className="flex items-center gap-2 text-sm text-[var(--color-text-dim)]">
            τ = <span className="font-mono text-[var(--color-text)]">{tau.toFixed(2)}</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={tau}
              onChange={(e) => setTau(parseFloat(e.target.value))}
              className="w-32 accent-[var(--color-accent)]"
            />
          </label>
        )}
      </div>

      {totalRuns === 0 ? (
        <p className="mt-6 text-[var(--color-text-dim)]">
          Loading saved rollouts… If this stays empty, the backend has no rollouts.
        </p>
      ) : (
        <>
          {/* Teacher-prompt experiment — placed first since it's the most
              actionable comparison on the page right now. */}
          <PromptComparisonSection
            runs={runs}
            metric={metric}
            tau={tau}
            yLabel={yLabel}
            yFmt={yFmt}
          />

          {/* Headline KPI cards */}
          <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard label="Rollouts" value={String(totalRuns)} sub={`${models.length} models`} />
            <KpiCard
              label="Mean@1 (all)"
              value={overallMean !== null ? overallMean.toFixed(2) : "—"}
              sub="across all rollouts"
            />
            <KpiCard
              label="Pass@0.75"
              value={overallPassRate !== null ? `${(overallPassRate * 100).toFixed(1)}%` : "—"}
              sub="overall rollouts ≥ 0.75"
            />
            <KpiCard
              label="Best teacher"
              value={bestModel ? displayModel(bestModel.id) : "—"}
              sub={bestModel ? `mean@1 = ${bestModel.value.toFixed(2)}` : ""}
              valueColor={bestModel ? MODEL_COLOR[bestModel.id] : undefined}
            />
          </div>

          {/* Chart 1 */}
          <section className="mt-8">
            <div className="flex items-baseline justify-between gap-4 flex-wrap mb-2">
              <h3 className="text-base font-semibold">
                {yLabel} by model ·{" "}
                <span className="text-[var(--color-text-dim)] font-normal">
                  {criterion === "Overall" ? "Overall" : prettyCriterionId(criterion)}
                </span>
              </h3>
              <span className="text-xs text-[var(--color-text-dim)]">
                click a bar to drill into rollouts
              </span>
            </div>
            <CriterionTabs
              tabs={criteria}
              active={criterion}
              onSelect={setCriterion}
              renderLabel={(t) => (t === "Overall" ? "Overall" : prettyCriterionId(t))}
            />
            <div className="mt-4 flex justify-center">
              <SingleBarChart
                bars={models.map((m) => {
                  const b = cell[m]?.[criterion];
                  const mean = meanOf(b);
                  const v = val(b);
                  const label = displayModel(m) + " · " + (criterion === "Overall" ? "Overall" : prettyCriterionId(criterion));
                  return {
                    id: m,
                    label: displayModel(m),
                    sublabel: b ? `n = ${b.n}${b.nullN ? `  (${b.nullN} n/a)` : ""}` : "",
                    value: v,
                    color: MODEL_COLOR[m] ?? "#9aa0a6",
                    tooltip: statsTooltip(label, b, mean),
                    onClick: () => onDrillToModel(m),
                  };
                })}
                yLabel={yLabel}
                yFmt={yFmt}
              />
            </div>
          </section>

          {/* Chart 2 */}
          <section className="mt-10 mb-4">
            <div className="flex items-baseline justify-between gap-4 flex-wrap mb-2">
              <h3 className="text-base font-semibold">
                {yLabel} by criterion ·{" "}
                <span className="text-[var(--color-text-dim)] font-normal">{chart2Model}</span>
              </h3>
            </div>
            <CriterionTabs
              tabs={["All Models", ...models.map((m) => displayModel(m))]}
              active={chart2Model}
              onSelect={setChart2Model}
              renderLabel={(t) => t}
            />
            <div className="mt-4 flex justify-center">
              {chart2Model === "All Models" ? (
                <GroupedBarChart
                  groups={criteria.map((c) => ({
                    label: c === "Overall" ? "Overall" : prettyCriterionId(c),
                    bars: models.map((m) => {
                      const b = cell[m]?.[c];
                      const mean = meanOf(b);
                      const v = val(b);
                      const cl = c === "Overall" ? "Overall" : prettyCriterionId(c);
                      return {
                        id: m,
                        label: displayModel(m),
                        value: v,
                        color: MODEL_COLOR[m] ?? "#9aa0a6",
                        tooltip: statsTooltip(`${displayModel(m)} · ${cl}`, b, mean),
                        onClick: () => onDrillToModel(m),
                      };
                    }),
                  }))}
                  legend={models.map((m) => ({ label: displayModel(m), color: MODEL_COLOR[m] ?? "#9aa0a6" }))}
                  yLabel={yLabel}
                  yFmt={yFmt}
                />
              ) : (
                (() => {
                  const m = models.find((x) => displayModel(x) === chart2Model)!;
                  return (
                    <SingleBarChart
                      bars={criteria.map((c) => {
                        const b = cell[m]?.[c];
                        const mean = meanOf(b);
                        const v = val(b);
                        const cl = c === "Overall" ? "Overall" : prettyCriterionId(c);
                        return {
                          id: c,
                          label: cl,
                          sublabel: b ? `n = ${b.n}${b.nullN ? `  (${b.nullN} n/a)` : ""}` : "",
                          value: v,
                          color: CRITERION_COLOR[c] ?? "#9aa0a6",
                          tooltip: statsTooltip(`${displayModel(m)} · ${cl}`, b, mean),
                        };
                      })}
                      yLabel={yLabel}
                      yFmt={yFmt}
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
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-panel)] rounded-md px-4 py-3">
      <div className="text-xs uppercase tracking-wider text-[var(--color-text-dim)]">{label}</div>
      <div className="text-2xl font-bold mt-1" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </div>
      {sub && <div className="text-xs text-[var(--color-text-dim)] mt-0.5">{sub}</div>}
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

type BarDatum = {
  id: string;
  label: string;
  sublabel?: string;
  value: number | null;
  color: string;
  tooltip?: string; // shown via native SVG <title> on hover
  onClick?: () => void;
};

// ---- Teacher-prompt comparison ------------------------------------------
// Top section of the Results page. Filters rollouts to those participating
// in the prompt experiment (anything with a non-empty `prompt_name`, OR
// matching the `experiment_optimized__` id prefix). Bars: 4 prompts per
// teacher, grouped by teacher. Respects the page's Mean@1 / Pass@τ toggle.

const PROMPT_ORDER: string[] = ["default", "socratic", "concise", "optimized"];

const PROMPT_DISPLAY: Record<string, string> = {
  default: "Default",
  socratic: "Socratic",
  concise: "Concise",
  optimized: "Optimized",
  materials_first: "Materials-first",
  custom: "Custom",
};

// Distinct from MODEL_COLOR (which is used for model legend elsewhere).
const PROMPT_COLOR: Record<string, string> = {
  default: "#9aa0a6",       // grey
  socratic: "#a78bfa",      // purple
  concise: "#fbbf24",       // amber
  optimized: "#14b8a6",     // teal
  materials_first: "#f472b6", // pink
  custom: "#94a3b8",        // slate
};

function _isExperiment(r: RunSummary): boolean {
  // Treat any run with an explicit non-default prompt name as part of the
  // experiment view. The 60-rollout teacher-prompt batch was named with
  // an `experiment_optimized__` prefix, so we ALSO include its default-
  // prompt rollouts (which would otherwise be filtered out).
  if (r.id.startsWith("experiment_optimized__")) return true;
  if (r.prompt_name && r.prompt_name !== "default") return true;
  return false;
}

function PromptComparisonSection({
  runs,
  metric,
  tau,
  yLabel,
  yFmt,
}: {
  runs: RunSummary[];
  metric: Metric;
  tau: number;
  yLabel: string;
  yFmt: (v: number) => string;
}) {
  // Filter to experiment rollouts so prompts have apples-to-apples task coverage.
  const exp = runs.filter(_isExperiment);
  if (exp.length === 0) return null;

  // Aggregate (model, prompt) buckets.
  const cell: Record<string, Record<string, Bucket>> = {};
  for (const r of exp) {
    const p = r.prompt_name || "default";
    cell[r.model] ??= {};
    cell[r.model][p] ??= newBucket();
    addToBucket(cell[r.model][p], r.composite);
  }
  const models = TEACHER_MODELS.map((m) => m.id).filter((m) => cell[m]);
  const prompts = PROMPT_ORDER.filter((p) =>
    Object.values(cell).some((row) => row[p] && row[p].n > 0)
  );

  const groups = models.map((m) => ({
    label: displayModel(m),
    bars: prompts.map((p) => {
      const b = cell[m]?.[p];
      const mean = meanOf(b);
      const v = b ? (metric === "mean@1" ? mean : passAtOf(b, tau)) : null;
      return {
        id: `${m}::${p}`,
        label: PROMPT_DISPLAY[p] ?? p,
        value: v,
        color: PROMPT_COLOR[p] ?? "#9aa0a6",
        tooltip: statsTooltip(`${displayModel(m)} · ${PROMPT_DISPLAY[p] ?? p}`, b, mean),
      };
    }),
  }));
  const legend = prompts.map((p) => ({
    label: PROMPT_DISPLAY[p] ?? p,
    color: PROMPT_COLOR[p] ?? "#9aa0a6",
  }));

  const n = exp.length;
  return (
    <section className="mt-6 text-left">
      <h3 className="text-base font-semibold text-center">
        Teacher-prompt experiment ·{" "}
        <span className="text-[var(--color-text-dim)] font-normal">{yLabel}</span>
      </h3>
      <p className="mt-1 mx-auto max-w-3xl text-sm text-[var(--color-text-dim)] text-center">
        Same set of {Math.max(1, Math.round(n / (prompts.length * models.length || 1)))} tasks rolled
        out with each of {prompts.length} teacher system prompts across {models.length} teachers
        (n = {n} total). Bars show each prompt's effect per teacher; hover for
        sample size + range. Models that can't internalize a dense rule-list
        (e.g. nano) often do worse with the directive `Optimized` prompt.
      </p>
      <div className="mt-4 flex justify-center">
        <GroupedBarChart groups={groups} legend={legend} yLabel={yLabel} yFmt={yFmt} />
      </div>
    </section>
  );
}

function SingleBarChart({
  bars,
  yLabel,
  yFmt,
  tilt,
}: {
  bars: BarDatum[];
  yLabel: string;
  yFmt?: (v: number) => string;
  tilt?: boolean;
}) {
  if (!bars.length) {
    return <p className="text-sm text-[var(--color-text-dim)]">No data.</p>;
  }
  const fmt = yFmt ?? ((v: number) => v.toFixed(2));
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
    <div className="w-full max-w-4xl mx-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full h-auto">
        {yTicks.map((t) => {
          const y = padT + innerH - innerH * t;
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--color-border)" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="12" fill="var(--color-text-dim)">
                {fmt(t)}
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
          const cx = x + barW / 2;
          const clickable = !!d.onClick;
          return (
            <g key={d.id} className={clickable ? "cursor-pointer" : undefined} onClick={d.onClick}>
              {/* Native SVG tooltip with summary stats on hover */}
              {d.tooltip && <title>{d.tooltip}</title>}
              {/* Invisible click-target spans the full column for easier hover/hit area */}
              <rect x={x} y={padT} width={barW} height={innerH} fill="transparent" />
              {d.value !== null ? (
                <>
                  <path d={topRoundedPath(x, y, barW, h, 4)} fill={d.color} />
                  <text x={cx} y={y - 6} textAnchor="middle" fontSize="13" fill="var(--color-text)" fontWeight={600}>
                    {fmt(d.value)}
                  </text>
                </>
              ) : (
                <text x={cx} y={padT + innerH - 6} textAnchor="middle" fontSize="12" fill="var(--color-text-dim)">
                  n/a
                </text>
              )}
              {tilt ? (
                <text
                  x={cx}
                  y={padT + innerH + 14}
                  textAnchor="end"
                  fontSize="12"
                  fill="var(--color-text)"
                  transform={`rotate(-30 ${cx} ${padT + innerH + 14})`}
                >
                  {d.label}
                </text>
              ) : (
                <>
                  <text x={cx} y={padT + innerH + 22} textAnchor="middle" fontSize="13" fill="var(--color-text)">
                    {d.label}
                  </text>
                  {d.sublabel ? (
                    <text x={cx} y={padT + innerH + 40} textAnchor="middle" fontSize="11" fill="var(--color-text-dim)">
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
  yFmt,
}: {
  groups: {
    label: string;
    bars: {
      id: string;
      label: string;
      value: number | null;
      color: string;
      tooltip?: string;
      onClick?: () => void;
    }[];
  }[];
  legend: { label: string; color: string }[];
  yLabel: string;
  yFmt?: (v: number) => string;
}) {
  const fmt = yFmt ?? ((v: number) => v.toFixed(2));
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
    <div className="w-full max-w-5xl mx-auto">
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs mb-2 text-[var(--color-text-dim)]">
        {legend.map((l) => (
          <span key={l.label} className="inline-flex items-center gap-1.5">
            <span style={{ background: l.color, width: 10, height: 10, borderRadius: 2, display: "inline-block" }} />
            {l.label}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full h-auto">
        {yTicks.map((t) => {
          const y = padT + innerH - innerH * t;
          return (
            <g key={t}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--color-border)" />
              <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="12" fill="var(--color-text-dim)">
                {fmt(t)}
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
                const clickable = !!d.onClick;
                return (
                  <g
                    key={d.id}
                    className={clickable ? "cursor-pointer" : undefined}
                    onClick={d.onClick}
                  >
                    {d.tooltip && <title>{d.tooltip}</title>}
                    <rect x={x} y={padT} width={barW} height={innerH} fill="transparent" />
                    {d.value !== null ? (
                      <path d={topRoundedPath(x, y, barW, h, 3)} fill={d.color} />
                    ) : null}
                  </g>
                );
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
