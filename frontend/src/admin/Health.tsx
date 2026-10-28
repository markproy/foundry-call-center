import { useEffect, useState } from "react";
import { HealthData, adminGet } from "./adminApi";

export const ms = (v?: number | null) => (v == null ? "-" : v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`);

function Stat({ label, value, sub, bad }: { label: string; value: string | number; sub?: string; bad?: boolean }) {
  return (
    <div className={`stat${bad ? " bad" : ""}`}>
      <div className="v">{value}</div>
      <div className="l">{label}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  );
}

function Bars({ data }: { data: HealthData["series"] }) {
  const max = Math.max(1, ...data.map((d) => d.turns));
  return (
    <div className="bars">
      {data.map((d) => (
        <div key={d.t} className="bar" title={`${new Date(d.t).toLocaleString()}: ${d.turns} turns, ${d.errors} errors, p95 ${ms(d.total_p95)}`}>
          <div className="fill" style={{ height: `${(d.turns / max) * 100}%` }}>
            {d.errors > 0 && <div className="errfill" style={{ height: `${(d.errors / d.turns) * 100}%` }} />}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Health({ onDrill }: { onDrill: (tab: "traces", f: { intent?: string; errors?: boolean }) => void }) {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<HealthData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    adminGet<HealthData>("health", { hours }).then(setData, (e) => setError(String(e)));
  }, [hours]);

  if (error) return <p className="err">{error}</p>;
  if (!data) return <p className="pad">Loading…</p>;
  const t = data.totals;
  const errRate = t.turns ? ((t.errors ?? 0) / t.turns) * 100 : 0;
  const maxCalls = Math.max(1, ...data.tools.map((x) => x.calls));

  return (
    <div className="pad">
      <div className="toolbar">
        Window{" "}
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={1}>1 hour</option>
          <option value={24}>24 hours</option>
          <option value={168}>7 days</option>
          <option value={720}>30 days</option>
        </select>
      </div>
      <div className="stats">
        <Stat label="Turns" value={t.turns ?? 0} sub={`${t.members ?? 0} members`} />
        <Stat label="Error rate" value={`${errRate.toFixed(1)}%`} sub={`${t.errors ?? 0} failed`} bad={errRate > 2} />
        <Stat label="Guardrail blocks" value={t.guardrail_blocks ?? 0} />
        <Stat label="Total latency p50 / p95" value={`${ms(t.total_p50)} / ${ms(t.total_p95)}`} />
        <Stat label="First token p50 / p95" value={`${ms(t.ttft_p50)} / ${ms(t.ttft_p95)}`} />
        <Stat label="Routing p50 / p95" value={`${ms(t.classify_p50)} / ${ms(t.classify_p95)}`} />
        <Stat label="Tokens in / out" value={`${((t.input_tokens ?? 0) / 1000).toFixed(0)}k / ${((t.output_tokens ?? 0) / 1000).toFixed(0)}k`} />
        <Stat label="Est. cost" value={`$${(t.cost_usd ?? 0).toFixed(3)}`} sub={t.turns ? `$${((t.cost_usd ?? 0) / t.turns).toFixed(4)} per turn` : undefined} />
      </div>

      <h2>Turns over time <small>(red = failed)</small></h2>
      <Bars data={data.series} />

      <h2>By intent</h2>
      <table>
        <thead>
          <tr><th>Intent</th><th>Agent</th><th>Turns</th><th>Errors</th><th>p95 latency</th><th>Est. cost</th><th /></tr>
        </thead>
        <tbody>
          {data.by_intent.map((r, i) => (
            <tr key={i}>
              <td>{r.intent || "(none)"}</td><td>{r.agent || "-"}</td><td>{r.turns}</td><td>{r.errors}</td>
              <td>{ms(r.total_p95)}</td><td>${r.cost_usd.toFixed(4)}</td>
              <td><button className="link" onClick={() => onDrill("traces", { intent: r.intent })}>traces</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Tool use</h2>
      {data.tools.map((x, i) => (
        <div key={i} className="hbar">
          <span className="name">{x.agent.replace("-specialist", "")} / {x.tool}</span>
          <span className="track"><span style={{ width: `${(x.calls / maxCalls) * 100}%` }} /></span>
          <span className="n">{x.calls}</span>
        </div>
      ))}

      <h2>Failures</h2>
      {data.failures.length === 0 ? (
        <p>None in this window.</p>
      ) : (
        <table>
          <thead><tr><th>Stage</th><th>Agent</th><th>Error</th><th>Count</th><th>Last seen</th></tr></thead>
          <tbody>
            {data.failures.map((f, i) => (
              <tr key={i}><td>{f.stage}</td><td>{f.agent || "-"}</td><td>{f.error_type || "-"}</td><td>{f.failures}</td><td>{new Date(f.last_seen).toLocaleString()}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <p><button className="link" onClick={() => onDrill("traces", { errors: true })}>View failed traces</button></p>
    </div>
  );
}
