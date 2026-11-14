export interface PlanDraft {
  available_capital: string;
  available_cash: string;
  max_risk_amount: string;
  max_risk_percent: string;
  max_position_percent: string;
  cost_bps: string;
  scale_in_prices: string;
  take_profit_prices: string;
}

export interface ManualInput {
  entry: string;
  stop: string;
  target: string;
  action: string;
}

export interface PlanSession {
  analysisId: string;
  draft: PlanDraft;
  baseline: string;
  manual: ManualInput;
  manualBaseline: string;
  preview: unknown;
  previewToken: number;
  issuedToken: number;
  stale: boolean;
  saveAsDefault: boolean;
  selectedVersion: number | null;
}

const sessions = new Map<string, PlanSession>();
const listeners = new Set<() => void>();

export function blankManual(): ManualInput {
  return { entry: "", stop: "", target: "", action: "Buy" };
}

export function subscribePlanSessions(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(): void {
  for (const listener of listeners) listener();
}

export function readSession(analysisId: string): PlanSession | null {
  return sessions.get(analysisId) ?? null;
}

export function sessionKey(analysisId?: string): string {
  return analysisId || "new";
}

export function hydrateSession(analysisId: string, draft: PlanDraft): PlanSession {
  const existing = sessions.get(analysisId);
  if (existing) return existing;
  const manual = blankManual();
  const session: PlanSession = {
    analysisId,
    draft,
    baseline: JSON.stringify(draft),
    manual,
    manualBaseline: JSON.stringify(manual),
    preview: null,
    previewToken: 0,
    issuedToken: 0,
    stale: false,
    saveAsDefault: false,
    selectedVersion: null,
  };
  sessions.set(analysisId, session);
  emit();
  return session;
}

export function sessionDirty(session: PlanSession | null): boolean {
  if (!session) return false;
  return JSON.stringify(session.draft) !== session.baseline
    || JSON.stringify(session.manual) !== session.manualBaseline
    || session.saveAsDefault;
}

function replace(analysisId: string, session: PlanSession): PlanSession {
  sessions.set(analysisId, session);
  emit();
  return session;
}

export function editDraft(analysisId: string, draft: PlanDraft): void {
  const current = sessions.get(analysisId);
  if (!current) return;
  replace(analysisId, {
    ...current,
    draft,
    stale: true,
    preview: null,
    previewToken: 0,
    issuedToken: current.issuedToken + 1,
  });
}

export function editManual(analysisId: string, manual: ManualInput): void {
  const current = sessions.get(analysisId);
  if (!current) return;
  replace(analysisId, {
    ...current,
    manual,
    preview: null,
    previewToken: 0,
    issuedToken: current.issuedToken + 1,
  });
}

export function setSaveAsDefault(analysisId: string, saveAsDefault: boolean): void {
  const current = sessions.get(analysisId);
  if (!current) return;
  replace(analysisId, { ...current, saveAsDefault });
}

export function setSelectedVersion(analysisId: string, selectedVersion: number | null): void {
  const current = sessions.get(analysisId);
  if (!current) return;
  replace(analysisId, { ...current, selectedVersion });
}

export function beginPreview(analysisId: string): number {
  const current = sessions.get(analysisId);
  if (!current) return 0;
  const token = current.issuedToken + 1;
  replace(analysisId, { ...current, issuedToken: token, preview: null, previewToken: 0 });
  return token;
}

export function shouldApplyPreview(analysisId: string, token: number): boolean {
  const current = sessions.get(analysisId);
  return Boolean(current && current.issuedToken === token);
}

export function commitPreview(analysisId: string, token: number, preview: unknown): boolean {
  const current = sessions.get(analysisId);
  if (!current || current.issuedToken !== token) return false;
  replace(analysisId, { ...current, preview, previewToken: token });
  return true;
}

export function markSaved(analysisId: string, draft: PlanDraft): void {
  const current = sessions.get(analysisId);
  if (!current) return;
  replace(analysisId, {
    ...current,
    draft,
    baseline: JSON.stringify(draft),
    manualBaseline: JSON.stringify(current.manual),
    stale: false,
    saveAsDefault: false,
  });
}

export function discardSession(analysisId: string): void {
  sessions.delete(analysisId);
  emit();
}
