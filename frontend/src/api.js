// Points at the deployed Cloud Run service, never localhost. Vite bakes this
// in at build time, so a rebuild is required after changing it.
const BASE = import.meta.env.VITE_API_BASE_URL;

if (!BASE) {
  console.error("VITE_API_BASE_URL is not set. Copy .env.example to .env");
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });

  const body = await res.json().catch(() => null);

  if (!res.ok) {
    // The API returns one error shape everywhere, so unwrap it once here
    // rather than in every caller.
    const err = body?.error;
    throw new Error(err?.message || `Request failed (${res.status})`);
  }
  return body;
}

export const listPolicies = () => request("/api/policies");

export const createCase = (payload) =>
  request("/api/cases", { method: "POST", body: JSON.stringify(payload) });

export const getCase = (caseId) => request(`/api/cases/${caseId}`);

export const createAppeal = (caseId) =>
  request(`/api/cases/${caseId}/appeal`, { method: "POST" });

// Analysis takes 10 to 30 seconds once the agents are real, so the result is
// polled rather than awaited. Building it this way now means nothing changes
// in the UI when the stub is replaced.
export async function pollCase(caseId, { intervalMs = 2000, timeoutMs = 120000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await getCase(caseId);
    if (result.status === "complete") return result;
    if (result.status === "failed") {
      throw new Error("Analysis could not be completed. Try again.");
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("Analysis is taking longer than expected. Try again.");
}
