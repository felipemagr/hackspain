import { API_URL } from "./chat";

// The page is a static site: an error in someone's browser reaches nobody unless it is sent.
// It goes to the API log, best effort, and never gets in the way of the page.
export function reportError(source: "render" | "window" | "promise", error: unknown, stack?: string) {
  const err = error instanceof Error ? error : new Error(String(error));
  const body = JSON.stringify({
    source,
    message: err.message,
    url: window.location.pathname + window.location.search,
    stack: stack ?? err.stack,
  });
  fetch(`${API_URL}/api/v1/client-errors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {});
}

export function watchWindowErrors() {
  window.addEventListener("error", (e) => reportError("window", e.error ?? e.message));
  window.addEventListener("unhandledrejection", (e) => reportError("promise", e.reason));
}
