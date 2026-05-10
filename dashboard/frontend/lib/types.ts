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

export interface RunDetail {
  id: string;
  task_id: string | null;
  topic: string | null;
  rubric: RubricCriterion[] | null;
  messages: Message[];
  reward: number | null;
  judge_breakdown: JudgeBreakdown | null;
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
