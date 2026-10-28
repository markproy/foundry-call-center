export interface Turn {
  role: "user" | "assistant";
  content: string;
}

export interface DoneEvent {
  intent?: string;
  tools?: string[];
  guardrail?: string | null;
  agent?: string;
  classify_ms?: number;
  ttft_ms?: number | null;
  total_ms?: number;
}

/** Best-effort: starts the member's agent sessions so the first message is fast. */
export async function warmup(memberId: string): Promise<void> {
  const secret = sessionStorage.getItem("demo-secret");
  try {
    await fetch("/api/warmup", {
      method: "POST",
      headers: { "content-type": "application/json", ...(secret ? { "x-demo-secret": secret } : {}) },
      body: JSON.stringify({ member_id: memberId }),
    });
  } catch {
    /* ignore */
  }
}

/** Streams one chat turn. The caller sends the whole conversation each time. */
export async function streamChat(
  memberId: string,
  messages: Turn[],
  sessionId: string,
  on: { delta: (t: string) => void; replace: (t: string) => void; status: (t: string) => void; done: (e: DoneEvent) => void; error: (m: string) => void },
  signal?: AbortSignal,
): Promise<void> {
  const secret = sessionStorage.getItem("demo-secret");
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json", ...(secret ? { "x-demo-secret": secret } : {}) },
    body: JSON.stringify({ member_id: memberId, session_id: sessionId, messages }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    on.error(resp.status === 401 ? "Unauthorized (demo secret)" : `HTTP ${resp.status}`);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      let ev: Record<string, unknown>;
      try {
        ev = JSON.parse(line.slice(5));
      } catch {
        continue;
      }
      if (ev.type === "text_delta") on.delta(ev.text as string);
      else if (ev.type === "status") on.status(ev.text as string);
      else if (ev.type === "replace") on.replace(ev.text as string);
      else if (ev.type === "done") on.done(ev as DoneEvent);
      else if (ev.type === "error") on.error(ev.error as string);
    }
  }
}
