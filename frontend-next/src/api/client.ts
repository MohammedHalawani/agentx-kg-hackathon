import type { ApiSession } from "@/api/contracts";

/** A failed backend call. `status` 0 means the request never reached the backend. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
  /** The case changed underneath the operator, or the backend refused the action. */
  get conflict() {
    return this.status === 409;
  }
  get unavailable() {
    return this.status === 0 || this.status === 503 || this.status === 502;
  }
}

export interface ApiClientOptions {
  /** API origin. Empty means the page's own origin (the backend serves this app under /app/). */
  origin?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

function detailOf(body: unknown, fallback: string) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
      return detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item),
        )
        .join("; ");
  }
  return fallback;
}

export function idempotencyKey(prefix: string) {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replaceAll("-", "")
      : `${Date.now()}${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${random}`.slice(0, 64);
}

/**
 * Thin JSON client for the Suhail backend. It adds nothing to responses: no caching of
 * business state, no fallbacks, no fixture data. Errors surface as ApiError.
 */
export class ApiClient {
  private origin: string;
  private fetcher: typeof fetch;
  private timeoutMs: number;
  private session: Promise<ApiSession> | null = null;
  constructor(options: ApiClientOptions = {}) {
    this.origin = (options.origin ?? "").replace(/\/$/, "");
    this.fetcher = options.fetch ?? ((...args) => fetch(...args));
    this.timeoutMs = options.timeoutMs ?? 20000;
  }
  url(path: string, query?: Record<string, string | number | null | undefined>) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query ?? {}))
      if (value !== null && value !== undefined && value !== "")
        params.set(key, String(value));
    const text = params.toString();
    return `${this.origin}${path}${text ? `?${text}` : ""}`;
  }
  private async request<T>(
    method: "GET" | "POST",
    path: string,
    options: {
      query?: Record<string, string | number | null | undefined>;
      body?: unknown;
      headers?: Record<string, string>;
      timeoutMs?: number;
    } = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      options.timeoutMs ?? this.timeoutMs,
    );
    let response: Response;
    try {
      response = await this.fetcher(this.url(path, options.query), {
        method,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(options.body === undefined
            ? {}
            : { "Content-Type": "application/json" }),
          ...options.headers,
        },
        body:
          options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      throw new ApiError(
        0,
        controller.signal.aborted
          ? "The Suhail backend did not answer in time."
          : "The Suhail backend is not reachable.",
        path,
      );
    } finally {
      clearTimeout(timer);
    }
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* A non-JSON body is reported through the status alone. */
    }
    if (!response.ok)
      throw new ApiError(
        response.status,
        detailOf(body, `The backend answered ${response.status}.`),
        path,
      );
    return body as T;
  }
  get<T>(path: string, query?: Record<string, string | number | null | undefined>) {
    return this.request<T>("GET", path, { query });
  }
  /** The local operations session. The backend chooses the actor; the browser cannot. */
  getSession(force = false) {
    if (!this.session || force)
      this.session = this.request<ApiSession>(
        "GET",
        "/operations/session",
      ).catch((error) => {
        this.session = null;
        throw error;
      });
    return this.session;
  }
  /** A state-changing call. Requires the backend's session token; retried once if it rotated. */
  async post<T>(path: string, body?: unknown, timeoutMs?: number): Promise<T> {
    const send = async (force: boolean) => {
      const session = await this.getSession(force);
      return this.request<T>("POST", path, {
        body,
        timeoutMs,
        headers: { "X-Operations-Token": session.token },
      });
    };
    try {
      return await send(false);
    } catch (error) {
      // The token is per backend process: after a restart the first call is refused once.
      if (error instanceof ApiError && error.status === 403) return send(true);
      throw error;
    }
  }
}
