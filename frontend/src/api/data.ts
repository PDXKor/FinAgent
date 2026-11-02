import createClient from "openapi-fetch";

import type { components, paths } from "./generated/data";

export type Job = components["schemas"]["Job"];
export type IngestRun = components["schemas"]["IngestRun"];
export type JobStarted = components["schemas"]["JobStarted"];

// Same-origin path; the dev/prod proxy forwards it to FinAgentData. Absolute so it also
// resolves outside a browser page (tests).
export const DATA_BASE = "/api/data";
export const data = createClient<paths>({
  baseUrl: `${globalThis.location?.origin ?? ""}${DATA_BASE}`,
  fetch: (request) => globalThis.fetch(request), // late-bound so test interceptors apply
});

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Data or a thrown ApiError carrying FastAPI's `detail`. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  const message =
    typeof detail === "string"
      ? detail
      : response.status >= 500 && response.status !== 503
        ? `FinAgentData API unreachable or failing (HTTP ${response.status})`
        : `HTTP ${response.status}`;
  throw new ApiError(response.status, message);
}
