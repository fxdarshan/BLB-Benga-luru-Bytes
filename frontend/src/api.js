// Talks to the BLB API. Its address is built into the page from VITE_API_BASE_URL.

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

// A search can wait on the LLM for up to about 45 seconds, plus retries.
const SEARCH_TIMEOUT_MS = 60_000;
const OTHER_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  /**
   * @param {"network" | "timeout" | "rate_limited" | "invalid" | "unavailable" | "server"} kind
   * @param {string} message A plain message from the API, when it sent one.
   * @param {number | null} retryAfter Seconds to wait, for rate limits.
   */
  constructor(kind, message = "", retryAfter = null) {
    super(message || kind);
    this.kind = kind;
    this.retryAfter = retryAfter;
  }
}

function detailText(detail) {
  if (typeof detail === "string") return detail;
  // FastAPI lists each invalid field. Show the first, in plain words.
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "";
    return field ? `${field}: ${first.msg}` : String(first.msg ?? "");
  }
  return "";
}

async function request(path, { method = "GET", body, timeout = OTHER_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    throw new ApiError(error.name === "AbortError" ? "timeout" : "network");
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  if (response.status === 204) return null;
  try {
    data = await response.json();
  } catch {
    // A proxy error page, for example. The status code still says what happened.
  }
  if (response.ok) return data;

  const message = detailText(data?.detail);
  if (response.status === 429) {
    const wait = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
    throw new ApiError("rate_limited", message, Number.isFinite(wait) ? wait : null);
  }
  if (response.status === 422) throw new ApiError("invalid", message);
  if (response.status === 503) throw new ApiError("unavailable", message);
  throw new ApiError("server", message);
}

export const getHealth = () => request("/health");
export const getOptions = () => request("/options");
export const recommend = (preferences) =>
  request("/recommend", { method: "POST", body: preferences, timeout: SEARCH_TIMEOUT_MS });
/** The same search ranked by rating alone, at once, to show while the AI ranks it. */
export const shortlist = (preferences) =>
  request("/shortlist", { method: "POST", body: preferences });
/** Thumbs up or down on one result's explanation. The reply has no body. */
export const sendFeedback = (feedback) => request("/feedback", { method: "POST", body: feedback });
