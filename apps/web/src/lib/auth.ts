// The write token. A person opens the server with `?token=...`; we keep it in
// sessionStorage (this tab only), take it out of the address bar, and send it as a
// Bearer header on every write. See apps/server/src/openpipeline/security.py.

const KEY = "openpipeline.token";

// Used when sessionStorage is blocked, so the token still works for this page load.
let memoryToken: string | null = null;

export function getToken(): string | null {
  try {
    const stored = window.sessionStorage.getItem(KEY);
    if (stored) return stored;
  } catch {
    // Storage can be blocked or throw in private windows.
  }
  return memoryToken;
}

export function setToken(token: string): void {
  memoryToken = token;
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch {
    // Kept in memory above.
  }
}

export function clearToken(): void {
  memoryToken = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
}

/** The `Authorization` header for the stored token, or nothing when there is none. */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * If the URL has `?token=...`, store it and remove it from the address bar (the other
 * query parameters and the hash stay). Returns true when a token was taken.
 */
export function captureTokenFromUrl(
  loc: Pick<Location, "href"> = window.location,
  history: Pick<History, "replaceState"> = window.history,
): boolean {
  const url = new URL(loc.href);
  const token = url.searchParams.get("token");
  if (token === null) return false;
  url.searchParams.delete("token");
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  if (token.trim() === "") return false;
  setToken(token.trim());
  return true;
}

// Whether the "paste the token" dialog is open. A write that gets a 401 opens it.
let prompting = false;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function promptForToken(): void {
  prompting = true;
  emit();
}

export function dismissTokenPrompt(): void {
  prompting = false;
  emit();
}

export function subscribeTokenPrompt(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isPromptingForToken(): boolean {
  return prompting;
}
