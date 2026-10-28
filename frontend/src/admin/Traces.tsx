import { useEffect, useState } from "react";
import { TraceDetailData, TraceRow, adminGet } from "./adminApi";
import { ms } from "./Health";

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const [d, setD] = useState<TraceDetailData | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    adminGet<TraceDetailData>(`traces/${id}`).then(setD, (e) => setError(String(e)));
  }, [id]);
  if (error) return <div className="detail"><button className="link" onClick={onClose}>close</button><p className="err">{error}</p></div>;
  if (!d) return <div className="detail">Loading…</div>;
  const end = Math.max(1, ...d.spans.map((s) => s.start_ms + (s.duration_ms ?? 0)));
  let dims: Record<string, string> = {};
  try {
    dims = JSON.parse(d.turn?.dims ?? "{}");
  } catch {
    /* ignore */
  }
  return (
    <div className="detail">
      <div className="toolbar">
        <b>Trace {id.slice(0, 8)}</b> <span>{ms(end)}</span>
        <button className="link" onClick={onClose}>close</button>
      </div>
      {dims.user_message && (
        <div className="convo">
          <div className="u"><b>Member:</b> {dims.user_message}</div>
          <div className="a"><b>Reply:</b> {dims.answer}</div>
        </div>
      )}
      {!dims.user_message && <p className="muted">Message content capture is off for this deployment.</p>}
      <div className="wf">
        {d.spans.map((s) => (
          <div key={s.id} className="row" title={s.dims}>
            <span className="name" style={{ paddingLeft: s.depth * 14 }}>
              {s.name} {s.target && <small>{s.target}</small>}
            </span>
            <span className="track">
              <span
                className={`span ${s.ok ? "" : "fail"} k-${s.name === "chat_turn" ? "turn" : s.name === "classify" || s.name === "specialist" ? "stage" : "io"}`}
                style={{ left: `${(s.start_ms / end) * 100}%`, width: `${Math.max(0.5, ((s.duration_ms ?? 0) / end) * 100)}%` }}
              />
            </span>
            <span className="n">{ms(s.duration_ms)}</span>
          </div>
        ))}
      </div>
      <details>
        <summary>Turn attributes</summary>
        <pre>{JSON.stringify({ ...dims, answer: undefined, user_message: undefined }, null, 2)}</pre>
      </details>
    </div>
  );
}

export default function Traces({ initial }: { initial: { intent?: string; errors?: boolean } }) {
  const [hours, setHours] = useState(24);
  const [intent, setIntent] = useState(initial.intent ?? "");
  const [member, setMember] = useState("");
  const [errorsOnly, setErrorsOnly] = useState(!!initial.errors);
  const [rows, setRows] = useState<TraceRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setRows(null);
    setError("");
    adminGet<{ traces: TraceRow[] }>("traces", { hours, intent, member, errors_only: errorsOnly }).then(
      (r) => setRows(r.traces),
      (e) => setError(String(e)),
    );
  }, [hours, intent, member, errorsOnly]);

  return (
    <div className="pad split">
      <div className="list">
        <div className="toolbar">
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            <option value={1}>1h</option><option value={24}>24h</option><option value={168}>7d</option><option value={720}>30d</option>
          </select>
          <select value={intent} onChange={(e) => setIntent(e.target.value)}>
            <option value="">all intents</option>
            {["claims", "appointments", "pharmacy", "out_of_scope", "blocked"].map((i) => <option key={i}>{i}</option>)}
          </select>
          <input placeholder="MBR-DEMO-000117" value={member} onChange={(e) => setMember(e.target.value.trim())} />
          <label><input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} /> errors only</label>
        </div>
        {error && <p className="err">{error}</p>}
        {!rows ? <p>Loading…</p> : rows.length === 0 ? <p>No traces.</p> : (
          <table>
            <thead><tr><th>Time</th><th>Member</th><th>Intent</th><th>Message</th><th>Latency</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.operation_Id} className={`${selected === r.operation_Id ? "sel" : ""}${r.ok ? "" : " failrow"}`} onClick={() => setSelected(r.operation_Id)}>
                  <td>{new Date(r.timestamp).toLocaleTimeString()}</td>
                  <td>{r.member.slice(-3)}</td>
                  <td>{r.intent || "-"}{r.guard && " 🛡"}</td>
                  <td className="msg">{r.user_message || <span className="muted">{r.tools || "-"}</span>}</td>
                  <td>{ms(r.total)}</td>
                  <td>{r.ok ? "" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {selected && <Detail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
