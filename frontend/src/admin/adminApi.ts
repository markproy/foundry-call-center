const KEY = "admin-secret";

export const getSecret = () => localStorage.getItem(KEY) ?? "";
export const setSecret = (s: string) => localStorage.setItem(KEY, s);
export const clearSecret = () => localStorage.removeItem(KEY);

export class Forbidden extends Error {}

export async function adminGet<T>(path: string, params: Record<string, string | number | boolean> = {}): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  const resp = await fetch(`/api/admin/${path}?${qs}`, { headers: { "x-admin-secret": getSecret() } });
  if (resp.status === 403) throw new Forbidden();
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

export interface Totals {
  turns?: number;
  errors?: number;
  guardrail_blocks?: number;
  members?: number;
  total_p50?: number;
  total_p95?: number;
  ttft_p50?: number;
  ttft_p95?: number;
  classify_p50?: number;
  classify_p95?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
}

export interface HealthData {
  hours: number;
  totals: Totals;
  by_intent: { intent: string; agent: string; turns: number; errors: number; total_p95: number; input_tokens: number; output_tokens: number; cost_usd: number }[];
  series: { t: string; turns: number; errors: number; total_p95: number }[];
  tools: { agent: string; tool: string; calls: number }[];
  failures: { stage: string; agent: string; error_type: string; failures: number; last_seen: string }[];
}

export interface TraceRow {
  timestamp: string;
  operation_Id: string;
  member: string;
  session: string;
  intent: string;
  agent: string;
  tools: string;
  guard: string;
  total: number | null;
  ttft: number | null;
  ok: boolean;
  cost_usd: number;
  user_message: string;
}

export interface Span {
  id: string;
  parent: string;
  name: string;
  source: string;
  target: string;
  start_ms: number;
  duration_ms: number | null;
  ok: boolean;
  depth: number;
  dims: string;
}

export interface TraceDetailData {
  operation_id: string;
  turn: Span | null;
  spans: Span[];
}

export interface EvalRunRow {
  id: string;
  timestamp: string;
  pass_rate: number;
  threshold: number;
  total: number;
  passed: number;
  chat_url: string;
}

export interface EvalResult {
  id: string;
  message: string;
  passed: boolean;
  failures: string[];
  member_id?: string;
  expected_intent?: string | null;
  intent?: string;
  tools?: string[];
  total_ms?: number;
  answer?: string;
}

export interface EvalRunData extends EvalRunRow {
  results: EvalResult[];
}
