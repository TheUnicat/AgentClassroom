import type { Task, RunSummary, RunDetail, StreamEvent } from "./types";

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    getJson<{
      status: string;
      openai_key_set: boolean;
      runs_dir?: string;
      runs_dir_exists?: boolean;
      default_tutor_model?: string;
      default_student_model?: string;
      default_judge_model?: string;
    }>("/api/health"),
  listTasks: () => getJson<Task[]>("/api/tasks"),
  listRuns: () => getJson<RunSummary[]>("/api/runs"),
  getRun: (id: string) => getJson<RunDetail>(`/api/runs/${encodeURIComponent(id)}`),
};

/**
 * POST /api/run with SSE response. Yields parsed events as they arrive.
 *
 * Usage:
 *   for await (const evt of streamRun({ task_id })) { ... }
 */
export async function* streamRun(body: {
  task_id: string;
  tutor_model?: string;
  student_model?: string;
  judge_model?: string;
}): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${BACKEND_URL}/api/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${res.statusText} on /api/run`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // Normalize CRLF → LF up front so the separator scan only has to look for "\n\n".
    // Some SSE servers (incl. some proxy paths) emit \r\n line endings.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    // SSE: events are separated by a blank line. Each event has 'event:' and 'data:' lines.
    let separatorIdx;
    while ((separatorIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, separatorIdx);
      buffer = buffer.slice(separatorIdx + 2);

      let evtName = "message";
      const dataLines: string[] = [];
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) evtName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;

      let data: unknown = {};
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }

      yield { type: evtName as StreamEvent["type"], ...(data as object) } as StreamEvent;
    }
  }
}
