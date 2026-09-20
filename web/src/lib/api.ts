export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
// Baked into the bundle: this keeps strangers off the API, not a reader of the page.
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;
export const API_HEADERS: Record<string, string> = API_KEY ? { "X-API-Key": API_KEY } : {};
