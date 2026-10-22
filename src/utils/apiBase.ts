// The shared session cookie is scoped to `.replow.org`, so a request from
// admin.replow.org only carries it when the API is reached on the *same*
// origin. Calling https://api.4z.ink instead silently drops the cookie and
// every session restore looks like a dead login.
//
// Any first-party host under a domain that nginx proxies with `/v1` must
// therefore resolve to the relative `/v1` path. Everything else keeps the
// configured absolute base as a fallback.
const FALLBACK_API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "https://api.4z.ink/v1"
).replace(/\/$/, "");

const SAME_ORIGIN_API_DOMAINS = ["replow.org", "4z.ink"];

/** Resolve the API base for the current runtime origin. */
export function resolveApiBase(): string {
  if (typeof window === "undefined") return FALLBACK_API_BASE;
  const host = window.location.hostname.toLowerCase();
  const matched = SAME_ORIGIN_API_DOMAINS.some(
    domain => host === domain || host.endsWith("." + domain)
  );
  return matched ? "/v1" : FALLBACK_API_BASE;
}

export const replowApiBase = resolveApiBase();
