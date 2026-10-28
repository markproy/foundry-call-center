import { useEffect, useMemo, useState } from "react";
import { EvalResult, EvalRunData, EvalRunRow, adminGet } from "./adminApi";
import { ms } from "./Health";

function Run({ id }: { id: string }) {
  const [run, setRun] = useState<EvalRunData | null>(null);
  const [failedOnly, setFailedOnly] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    setRun(null);
    adminGet<EvalRunData>(`evals/${id}`).then(setRun);
  }, [id]);

  const byIntent = useMemo(() => {
    const m = new Map<string, { n: number; ok: number }>();
    for (const r of run?.results ?? []) {
      const k = r.expected_intent ?? "(unspecified)";
      const e = m.get(k) ?? { n: 0, ok: 0 };
      e.n++;
      if (r.passed) e.ok++;
      m.set(k, e);
    }
    return [...m.entries()];
  }, [run]);

  if (!run) return <p>Loading…</p>;
  const rows: EvalResult[] = run.results.filter((r) => !failedOnly || !r.passed);
  return (
    <div>
      <div className="stats">
        <div className="stat"><div className="v">{(run.pass_rate * 100).toFixed(0)}%</div><div className="l">{run.passed}/{run.total} passed</div></div>
        {byIntent.map(([k, v]) => (
          <div key={k} className={`stat${v.ok < v.n ? " bad" : ""}`}><div className="v">{v.ok}/{v.n}</div><div className="l">{k}</div></div>
        ))}
      </div>
      <div className="toolbar">
        <label><input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> failures only</label>
      </div>
      {rows.length === 0 ? <p>{failedOnly ? "No failing cases." : "No cases."}</p> : (
        <table>
          <thead><tr><th>Case</th><th>Member</th><th>Message</th><th>Intent</th><th>Latency</th><th>Result</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <>
                <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} className={r.passed ? "" : "failrow"}>
                  <td>{r.id}</td><td>{r.member_id?.slice(-3)}</td><td className="msg">{r.message}</td>
                  <td>{r.intent}{r.expected_intent && r.intent !== r.expected_intent ? ` (want ${r.expected_intent})` : ""}</td>
                  <td>{ms(r.total_ms)}</td><td>{r.passed ? "✓" : "✗"}</td>
                </tr>
                {open === r.id && (
                  <tr key={`${r.id}-d`}><td colSpan={6} className="expand">
                    {r.failures.length > 0 && <p className="err">{r.failures.join("; ")}</p>}
                    <p><b>Tools:</b> {(r.tools ?? []).join(", ") || "none"}</p>
                    <p className="answer">{r.answer}</p>
                  </td></tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Quality() {
  const [runs, setRuns] = useState<EvalRunRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    adminGet<{ runs: EvalRunRow[] }>("evals").then(
      (r) => {
        setRuns(r.runs);
        if (r.runs[0]) setSelected(r.runs[0].id);
      },
      (e) => setError(String(e)),
    );
  }, []);
  if (error) return <p className="err pad">{error}</p>;
  if (!runs) return <p className="pad">Loading…</p>;
  if (runs.length === 0) return <p className="pad">No eval runs yet. Run <code>COSMOS_ENDPOINT=... python eval/run_eval.py --url ...</code> to upload one.</p>;
  const max = 1;
  return (
    <div className="pad">
      <h2>Pass rate by run <small>(newest on the right; click a bar to open it)</small></h2>
      <div className="bars">
        {[...runs].reverse().map((r) => (
          <div key={r.id} className={`bar clickable${selected === r.id ? " selbar" : ""}`} onClick={() => setSelected(r.id)}
               title={`${r.id}: ${r.passed}/${r.total} (${(r.pass_rate * 100).toFixed(0)}%)`}>
            <div className="fill" style={{ height: `${(r.pass_rate / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="toolbar">
        Run{" "}
        <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value)}>
          {runs.map((r) => <option key={r.id} value={r.id}>{r.id} - {(r.pass_rate * 100).toFixed(0)}% ({r.passed}/{r.total})</option>)}
        </select>
      </div>
      {selected && <Run id={selected} />}
    </div>
  );
}
