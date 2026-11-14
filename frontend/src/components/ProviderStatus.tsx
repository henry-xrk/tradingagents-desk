import type { SystemStatus } from "../types/api.ts";

export type ProviderCode = "checking" | "unavailable" | "missing" | "unverified" | "passed" | "failed";

export function providerStatusCode(status: SystemStatus | undefined, pending = false, failed = false): ProviderCode {
  if (pending || !status) return "checking";
  if (failed) return "unavailable";
  if (!status.openai_api_key_configured) return "missing";
  const validation = status.validation;
  if (!validation.matches_current || validation.code === "not_checked" || validation.code === "stale") return "unverified";
  if (validation.ok) return "passed";
  return "failed";
}

export function providerCheckedAt(status: SystemStatus | undefined): string | null {
  if (!status?.validation.matches_current) return null;
  return status.validation.checked_at;
}
