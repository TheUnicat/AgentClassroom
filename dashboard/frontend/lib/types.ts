// Shared type definitions matching the FastAPI backend's JSON shape.

export interface Anchor {
  score: number | null;
  meaning: string;
}

export interface RubricCriterion {
  id: string;
  description: string;
  anchors: Anchor[];
}

export interface Task {
  task_id: string;
  subject: string;
  topic: string;
  difficulty: string;
  turns: number;
  rubric: RubricCriterion[];
  seed_question: string;
  has_materials: boolean;
  fixed_followup_count: number;
}

export interface RunSummary {
  id: string;
  task_id: string | null;
  topic: string | null;
  model: string;
  timestamp: string;
  composite: number;
  scores: Record<string, number | null> | null;
  rationale?: string | null;
  prompt_name?: string;  // "default" | "socratic" | "concise" | "optimized" | "materials_first" | "custom"
}

export interface Message {
  role: string; // "system" | "user" | "assistant" | "tool"
  content: string;
}

export interface JudgeBreakdown {
  scores: Record<string, number | null>;
  rationale?: string;
  composite?: number;
  rubric?: RubricCriterion[];
}

// One entry per teacher turn from the state_v1 composer.
// state_value = det-only running composite up to this teacher turn.
// turn_score  = state_value(t) - state_value(t-1), with t-1 = 0 convention.
// state_breakdown[crit] = running aggregate for that criterion at this turn.
// turn_breakdown[crit]  = change since prior turn (first-defined = the value itself).
export interface TrajectoryTurn {
  turn: number;
  msg_idx: number;
  state_value: number;
  turn_score: number;
  state_breakdown: Record<string, number | null>;
  turn_breakdown: Record<string, number | null>;
  // class A (per-turn-natural) immediate rewards — already per turn, no
  // running aggregate. Kept for hover insight.
  scores?: Record<string, number | null>;
  // class B (sequence-level cumulative) raw V(s_t) + delta — kept for inspection.
  state?: Record<string, number | null>;
  delta?: Record<string, number | null>;
}

export interface RunDetail {
  id: string;
  task_id: string | null;
  topic: string | null;
  rubric: RubricCriterion[] | null;
  messages: Message[];
  reward: number | null;
  judge_breakdown: JudgeBreakdown | null;
  trajectory: TrajectoryTurn[] | null;
  // Teacher system prompt — surfaced for the right-side prompt pill.
  // `name` is the registry key ("default" / "socratic" / "concise" /
  // "materials_first" / "optimized" / "custom"). `tutor_system_prompt`
  // is the raw text (empty when name is "default").
  tutor_system_prompt: string;
  tutor_system_prompt_name: string;
  metrics: Record<string, number> | null;
  stop_condition: string | null;
  is_completed: boolean | null;
}

export type StreamEvent =
  | { type: "info"; status: string; [k: string]: unknown }
  | { type: "message"; role: string; content: string }
  | {
      type: "done";
      reward: number;
      judge_breakdown: JudgeBreakdown;
      stop_condition: string | null;
      metrics: Record<string, number> | null;
    }
  | { type: "error"; error: string };
