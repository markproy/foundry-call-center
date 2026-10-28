import { useEffect, useState } from "react";
import { Forbidden, clearSecret, getSecret, setSecret, adminGet } from "./adminApi";
import Health from "./Health";
import Traces from "./Traces";
import Quality from "./Quality";
import "./admin.css";

type Tab = "health" | "traces" | "quality";

export function Admin() {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(!!getSecret());
  const [secret, setSecretInput] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("health");
  // Lets Health drill into Traces with a filter.
  const [traceFilter, setTraceFilter] = useState<{ intent?: string; errors?: boolean }>({});

  async function verify() {
    try {
      await adminGet("ping");
      setAuthed(true);
      setError("");
    } catch (e) {
      clearSecret();
      setError(e instanceof Forbidden ? "Wrong admin secret." : "Admin API unavailable.");
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (getSecret()) void verify();
  }, []);

  if (!authed) {
    return (
      <div className="adm login">
        <h1>Admin</h1>
        {checking ? (
          <p>Checking…</p>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setSecret(secret);
              void verify();
            }}
          >
            <input type="password" name="password" autoComplete="current-password" placeholder="Admin secret" value={secret} onChange={(e) => setSecretInput(e.target.value)} autoFocus />
            <button>Sign in</button>
          </form>
        )}
        <p className="muted">Remembered in this browser after sign-in; "Sign out" forgets it.</p>
        {error && <p className="err">{error}</p>}
        <a href="#/">Back to chat</a>
      </div>
    );
  }

  const go = (t: Tab, filter: { intent?: string; errors?: boolean } = {}) => {
    setTraceFilter(filter);
    setTab(t);
  };

  return (
    <div className="adm">
      <header>
        <h1>Foundry Call Center - Admin</h1>
        <nav>
          {(["health", "traces", "quality"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => go(t)}>
              {{ health: "System Health", traces: "Traces", quality: "Agent Quality" }[t]}
            </button>
          ))}
        </nav>
        <span>
          <a href="#/">Chat</a>{" "}
          <button className="link" onClick={() => { clearSecret(); setAuthed(false); }}>Sign out</button>
        </span>
      </header>
      {tab === "health" && <Health onDrill={go} />}
      {tab === "traces" && <Traces initial={traceFilter} />}
      {tab === "quality" && <Quality />}
    </div>
  );
}
