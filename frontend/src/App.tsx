import { useEffect, useRef, useState } from "react";
import { DoneEvent, Turn, streamChat, warmup } from "./api";
import { MEMBERS } from "./members";

interface Msg extends Turn {
  meta?: DoneEvent;
  failed?: boolean;
  status?: string;
}

export function App() {
  const [memberId, setMemberId] = useState(MEMBERS[0].id);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void warmup(memberId);
  }, [memberId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const member = MEMBERS.find((m) => m.id === memberId)!;

  function switchMember(id: string) {
    setMemberId(id);
    setMessages([]);
    setSessionId(crypto.randomUUID());
  }

  async function send(preset?: string) {
    const text = (preset ?? input).trim();
    if (!text || busy) return;
    const prior: Msg[] = messages.filter((m) => !m.failed);
    const history: Turn[] = [...prior, { role: "user" as const, content: text }].map(
      ({ role, content }) => ({ role, content }),
    );
    setMessages((m) => [
      ...m,
      { role: "user", content: text },
      { role: "assistant", content: "", status: "Understanding your request…" },
    ]);
    setInput("");
    setBusy(true);
    const patch = (fn: (m: Msg) => Msg) =>
      setMessages((all) => all.map((m, i) => (i === all.length - 1 ? fn(m) : m)));
    try {
      await streamChat(memberId, history, sessionId, {
        delta: (t) => patch((m) => ({ ...m, content: m.content + t, status: undefined })),
        status: (t) => patch((m) => ({ ...m, status: t })),
        replace: (t) => patch((m) => ({ ...m, content: t })),
        done: (meta) => patch((m) => ({ ...m, meta, status: undefined })),
        error: (e) => patch((m) => ({ ...m, content: m.content || e, failed: true, status: undefined })),
      });
    } catch {
      patch((m) => ({ ...m, content: m.content || "Network error.", failed: true, status: undefined }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>
          Foundry Call Center <a className="adminlink" href="#/admin">Admin</a>
        </h1>
        <label>
          Member{" "}
          <select value={memberId} onChange={(e) => switchMember(e.target.value)}>
            {MEMBERS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.id.slice(-3)}) - {m.scenario}
              </option>
            ))}
          </select>
        </label>
      </header>
      <main>
        {messages.length === 0 && (
          <p className="hint">
            Chatting as {member.name}. Ask about claims, appointments, or prescriptions.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}${m.failed ? " failed" : ""}`}>
            <div className="bubble">{m.content || (m.status ? "…" : "")}</div>
            {m.status && <div className="status">{m.status}</div>}
            {m.meta && (
              <div className="meta">
                {m.meta.intent}
                {m.meta.total_ms != null && ` · ${(m.meta.total_ms / 1000).toFixed(1)}s`}
                {m.meta.ttft_ms != null && ` · first token ${(m.meta.ttft_ms / 1000).toFixed(1)}s`}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </main>
      <div className="prompts">
        {member.prompts.map((p) => (
          <button key={p} type="button" className="chip" disabled={busy} onClick={() => void send(p)}>
            {p}
          </button>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Type a message" autoFocus />
        <button disabled={busy || !input.trim()}>Send</button>
      </form>
    </div>
  );
}
