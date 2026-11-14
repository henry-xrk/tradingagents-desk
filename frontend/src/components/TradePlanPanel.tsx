import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { useLocale } from "../i18n.tsx";
import { formatNumber, formatShares, parseOptionalNumber, parsePriceList, priceList } from "../lib/utils.ts";
import {
  beginPreview,
  commitPreview,
  editDraft,
  editManual,
  hydrateSession,
  markSaved,
  readSession,
  sessionKey,
  setSaveAsDefault,
  setSelectedVersion,
  shouldApplyPreview,
  subscribePlanSessions,
} from "../lib/planSession.ts";
import type { PlanDraft } from "../lib/planSession.ts";
import { ApiError, api } from "../services/api.ts";
import type { CapitalPreferences, FinalDecision, PlanVersionDetail, PositionSizeResult, TradePlan } from "../types/api.ts";
import { StatusText } from "./StatusText.tsx";
import { Button } from "./ui/button.tsx";
import { Input } from "./ui/input.tsx";

export function TradePlanPanel({
  analysisId,
  plan,
  decision,
}: {
  analysisId?: string;
  ticker?: string;
  plan: TradePlan | null | undefined;
  decision?: FinalDecision;
}) {
  const { t } = useLocale();
  const queryClient = useQueryClient();
  const key = sessionKey(analysisId);
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: ({ signal }) => api<CapitalPreferences>("/api/preferences", { signal }),
  });
  const session = useSyncExternalStore(subscribePlanSessions, () => readSession(key), () => readSession(key));
  useEffect(() => {
    if (preferences.data && !readSession(key)) hydrateSession(key, toDraft(preferences.data, plan?.input_snapshot));
  }, [preferences.data, key, plan]);
  const versions = useQuery({
    queryKey: ["plan-versions", analysisId],
    queryFn: ({ signal }) => api<{ version: number; created_at: string }[]>(`/api/analyses/${analysisId}/plan-versions`, { signal }),
    enabled: Boolean(analysisId),
  });
  const selectedVersion = session?.selectedVersion ?? null;
  const historical = useQuery({
    queryKey: ["plan-version", analysisId, selectedVersion],
    queryFn: ({ signal }) => api<PlanVersionDetail>(`/api/analyses/${analysisId}/plan-versions/${selectedVersion}`, { signal }),
    enabled: Boolean(analysisId && selectedVersion),
  });
  const [notice, setNotice] = useState<"idle" | "saved">("idle");
  const [calcError, setCalcError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);

  const save = useMutation({
    mutationFn: async (next: PlanDraft) => {
      const parsed = parseDraft(next, t);
      if (parsed.errors || !analysisId) throw new Error(t("field.required").replace("{label}", t("plan.capital")));
      return api<TradePlan>(`/api/analyses/${analysisId}/trade-plan`, {
        method: "POST",
        body: JSON.stringify({
          ...parsed.capital,
          ...parsed.prices,
          expected_plan_version: plan?.plan_version ?? null,
          save_as_default: session?.saveAsDefault ?? false,
        }),
      });
    },
    onSuccess: async () => {
      if (session?.draft) markSaved(key, session.draft);
      setNotice("saved");
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
      if (analysisId) {
        await queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] });
        await queryClient.invalidateQueries({ queryKey: ["plan-versions", analysisId] });
      }
    },
  });

  const draft = session?.draft;
  const manual = session?.manual ?? { entry: "", stop: "", target: "", action: "Buy" };
  const capitalErrors = draft ? capitalFieldErrors(draft, t) : {};
  const priceErrors = draft ? priceFieldErrors(draft, t) : {};
  const manualErrors = manualFieldErrors(manual, t);
  const unsupported = !["buy", "overweight"].includes(manual.action.toLowerCase());
  const conflict = save.error instanceof ApiError && save.error.status === 409;
  const preview = (session?.preview as PositionSizeResult | null) ?? null;
  const gap = planGap(decision, plan, t);

  function changeDraft(field: keyof PlanDraft, value: string) {
    if (!draft) return;
    setNotice("idle");
    editDraft(key, { ...draft, [field]: value });
  }

  async function calculate() {
    if (!draft || unsupported) return;
    const errors = { ...capitalFieldErrors(draft, t), ...manualFieldErrors(manual, t) };
    if (Object.values(errors).some(Boolean)) return;
    const parsed = parseDraft(draft, t);
    if (parsed.errors) return;
    const token = beginPreview(key);
    setCalcError(null);
    setCalculating(true);
    try {
      const result = await api<PositionSizeResult>("/api/position-size", {
        method: "POST",
        body: JSON.stringify({
          ...parsed.capital,
          ...parsed.prices,
          entry_price: parseOptionalNumber(manual.entry),
          stop_loss: parseOptionalNumber(manual.stop),
          price_target: parseOptionalNumber(manual.target),
          action: manual.action || null,
        }),
      });
      if (!commitPreview(key, token, result) || !shouldApplyPreview(key, token)) return;
    } catch (error) {
      if (shouldApplyPreview(key, token)) {
        setCalcError(error instanceof Error ? error.message : "The calculation failed.");
      }
    } finally {
      if (shouldApplyPreview(key, token)) setCalculating(false);
    }
  }

  return (
    <div className="space-y-6">
      {selectedVersion != null ? (
        <section aria-busy={historical.isFetching} className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-medium">{t("plan.versions")}</h3>
            <StatusText tone="warn">{t("plan.readonly")}</StatusText>
          </div>
          {historical.isFetching && <p className="text-sm text-muted">{t("plan.loadingVersion")}</p>}
          {historical.isError && (
            <div role="alert" className="space-y-2">
              <p className="text-sm text-danger">{t("plan.versionError")}</p>
              <Button type="button" variant="outline" onClick={() => historical.refetch()}>{t("common.retry")}</Button>
            </div>
          )}
          {historical.data && !historical.isError && (
            <>
              <p className="text-xs text-muted">{t("plan.saved")} {historical.data.created_at}</p>
              <DiffList snapshot={historical.data.snapshot} current={plan?.input_snapshot} empty={t("plan.noDiff")} title={t("plan.diff")} />
              <ResearchPlan plan={historical.data.plan} decision={undefined} t={t} />
            </>
          )}
        </section>
      ) : (
        <section className="space-y-3">
          <h3 className="text-sm font-medium">{t("plan.research")}</h3>
          {plan ? <ResearchPlan plan={plan} decision={decision} t={t} /> : <p className="text-sm text-muted">{t("research.noPlan")}</p>}
          <div className="rounded-md border border-line bg-canvas px-3 py-3">
            <h3 className="text-sm font-medium">{t("plan.status")}</h3>
            <p className="copy mt-1 text-sm">{gap.summary}</p>
            {gap.original && (
              <details className="mt-2 text-xs text-muted">
                <summary>{t("plan.original")}</summary>
                <p className="copy mt-1 whitespace-pre-wrap">{gap.original}</p>
              </details>
            )}
          </div>
        </section>
      )}

      <section className="space-y-3 border-t border-line pt-4">
        <h3 className="text-sm font-medium">{t("plan.versions")}</h3>
        {(versions.data?.length ?? 0) === 0 ? <p className="text-sm text-muted">{t("plan.noVersion")}</p> : (
          <VersionSelect
            versions={versions.data}
            value={selectedVersion}
            onChange={(value) => setSelectedVersion(key, value)}
            currentLabel={t("plan.current")}
          />
        )}
      </section>

      {selectedVersion == null && (
        <form
          className="space-y-4 border-t border-line pt-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft) return;
            if (Object.keys({ ...capitalFieldErrors(draft, t), ...priceFieldErrors(draft, t) }).length) return;
            save.mutate(draft);
          }}
        >
          <div>
            <h3 className="text-sm font-medium">{t("plan.capital")}</h3>
            <p className="copy mt-1 text-xs text-muted">{t("plan.capitalNote")}</p>
          </div>
          {!draft && <p className="text-sm text-muted">{t("plan.defaultsLoading")}</p>}
          {draft && <>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="capital" label={t("plan.account")} suffix={t("plan.moneyUnit")} value={draft.available_capital} error={capitalErrors.available_capital} onChange={(value) => changeDraft("available_capital", value)} />
            <Field id="cash" label={t("plan.cash")} suffix={t("plan.moneyUnit")} value={draft.available_cash} error={capitalErrors.available_cash} onChange={(value) => changeDraft("available_cash", value)} />
            <Field id="risk-amount" label={t("plan.riskAmount")} suffix={t("plan.moneyUnit")} value={draft.max_risk_amount} error={capitalErrors.max_risk_amount} onChange={(value) => changeDraft("max_risk_amount", value)} />
            <Field id="risk-percent" label={t("plan.riskPercent")} suffix="%" value={draft.max_risk_percent} error={capitalErrors.max_risk_percent} onChange={(value) => changeDraft("max_risk_percent", value)} />
            <Field id="position" label={t("plan.position")} suffix="%" value={draft.max_position_percent} error={capitalErrors.max_position_percent} onChange={(value) => changeDraft("max_position_percent", value)} />
            <Field id="cost" label={t("plan.cost")} suffix={t("plan.bps")} value={draft.cost_bps} error={capitalErrors.cost_bps} onChange={(value) => changeDraft("cost_bps", value)} />
          </div>
          <div className="grid gap-3">
            <h3 className="text-sm font-medium">{t("plan.prices")}</h3>
            <Field id="scale" label={t("plan.scale")} value={draft.scale_in_prices} error={priceErrors.scale_in_prices} onChange={(value) => changeDraft("scale_in_prices", value)} />
            <Field id="take" label={t("plan.take")} value={draft.take_profit_prices} error={priceErrors.take_profit_prices} onChange={(value) => changeDraft("take_profit_prices", value)} />
          </div>
          </>}
          {analysisId ? (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={session?.saveAsDefault ?? false}
                onChange={(event) => setSaveAsDefault(key, event.target.checked)}
              />
              <span>{t("plan.saveDefault")}</span>
            </label>
          ) : <p className="text-xs text-muted">{t("research.noPlan")}</p>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={!draft || !analysisId || save.isPending}>{save.isPending ? t("plan.saving") : t("plan.save")}</Button>
            <span role="status" className="text-xs text-muted">
              {save.isPending && t("plan.saving")}
              {!save.isPending && notice === "saved" && !session?.stale && t("plan.saved")}
              {session?.stale && t("plan.stale")}
            </span>
          </div>
          {conflict && (
            <div role="alert" className="space-y-2">
              <p className="text-sm text-danger">{t("plan.conflict")}</p>
              <Button type="button" variant="outline" onClick={() => queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] })}>{t("plan.reload")}</Button>
            </div>
          )}
          {save.isError && !conflict && <p role="alert" className="text-sm text-danger">{save.error.message}</p>}
        </form>
      )}

      <form
        className="space-y-3 border-t border-line pt-4"
        onSubmit={(event) => {
          event.preventDefault();
          void calculate();
        }}
      >
        <div>
          <h3 className="text-sm font-medium">{t("plan.manual")}</h3>
          <p className="copy mt-1 text-xs text-muted">{t("plan.manualNote")}</p>
        </div>
        <label className="block max-w-xs text-xs text-muted">
          {t("plan.action")}
          <select
            className="mt-1 h-9 w-full rounded-md border border-line-strong bg-paper px-2 text-sm text-ink"
            value={manual.action}
            onChange={(event) => editManual(key, { ...manual, action: event.target.value })}
          >
            <option>Buy</option>
            <option>Sell</option>
            <option>Hold</option>
            <option>Reduce</option>
          </select>
        </label>
        {unsupported ? (
          <p className="copy text-sm text-warn">{t("plan.unsupported")}</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field id="entry" label={t("plan.entry")} value={manual.entry} error={manualErrors.entry} onChange={(value) => editManual(key, { ...manual, entry: value })} />
              <Field id="stop" label={t("plan.stop")} value={manual.stop} error={manualErrors.stop} onChange={(value) => editManual(key, { ...manual, stop: value })} />
              <Field id="target" label={t("plan.target")} value={manual.target} error={manualErrors.target} onChange={(value) => editManual(key, { ...manual, target: value })} />
            </div>
            <Button type="submit" variant="outline" disabled={calculating}>{calculating ? t("plan.calculating") : t("plan.calculate")}</Button>
          </>
        )}
        {preview && session?.previewToken === session?.issuedToken && (
          <div className="rounded-md border border-line p-3 text-sm">
            <p className="text-xs text-muted">{t("plan.scenario")}</p>
            <dl className="mt-2 space-y-1">
              <Metric label={t("plan.shares")} value={formatShares(preview.sizing.shares)} />
              <Metric label={t("plan.capitalUsed")} value={formatNumber(preview.sizing.capital_used)} />
              <Metric label={t("plan.loss")} value={formatNumber(preview.sizing.planned_loss)} />
              <Metric label={t("plan.constraint")} value={(preview.sizing.binding_constraint ?? []).join(", ") || t("common.unknown")} />
              <Metric label={t("plan.cost")} value={`${draft?.cost_bps || "0"} ${t("plan.bps")}`} />
            </dl>
          </div>
        )}
        {session?.stale && !preview && <p className="text-xs text-warn">{t("plan.expired")}</p>}
        {calcError && <p role="alert" className="text-sm text-danger">{calcError}</p>}
      </form>
    </div>
  );
}

function ResearchPlan({ plan, decision, t }: { plan: TradePlan; decision?: FinalDecision; t: (key: string) => string }) {
  const fields = [
    ["entry_price", t("plan.entry"), plan.hypotheses?.entry_price],
    ["stop_loss", t("plan.stop"), plan.hypotheses?.stop_loss],
    ["price_target", t("plan.target"), plan.hypotheses?.price_target],
  ] as const;
  const states = fields.map(([key]) => decision?.price_fields?.[key] ?? (plan.hypotheses ? "missing" : "unknown"));
  const allEmpty = states.every((state) => state === "stated_absent" || state === "missing" || state === "unknown");
  const market = plan.verified_market;
  const calculation = plan.calculation_market;
  return (
    <div className="space-y-3 text-sm">
      {allEmpty ? <p className="copy text-sm">{t("plan.empty")}</p> : (
        <dl className="space-y-1">
          {fields.map(([key, label, value], index) => (
            <div key={key} className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-muted">{label}</dt>
              <dd className="num text-right text-xs">
                {states[index] === "available" || value != null ? formatNumber(value) : reasonForState(states[index], t)}
                <span className="ml-2 text-faint">{t("plan.sourceResearch")}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      <MarketLine title={market?.role === "stored_market_record" ? t("plan.stored") : t("plan.snapshot")} market={market} t={t} />
      {calculation && <MarketLine title={t("plan.calculation")} market={calculation} t={t} />}
    </div>
  );
}

function MarketLine({
  title,
  market,
  t,
}: {
  title: string;
  market: TradePlan["verified_market"] | NonNullable<TradePlan["calculation_market"]> | null | undefined;
  t: (key: string) => string;
}) {
  if (!market) return null;
  return (
    <p className="text-xs text-muted">
      {title}: {market.price == null ? t("common.unknown") : formatNumber(market.price)}
      {" · "}{t("plan.date")} {market.bar_date || t("common.unknown")}
      {" · "}{t("plan.currency")} {market.currency || t("common.unknown")}
      {!market.currency && ` · ${t("plan.currencyMissing")}`}
      {" · "}{t("plan.source")} {market.source || t("common.unknown")}
    </p>
  );
}

function VersionSelect({
  versions,
  value,
  onChange,
  currentLabel,
}: {
  versions: { version: number; created_at: string }[] | undefined;
  value: number | null;
  onChange: (value: number | null) => void;
  currentLabel: string;
}) {
  return (
    <select
      className="h-9 w-full max-w-md rounded-md border border-line-strong bg-paper px-2 text-sm"
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
      aria-label={currentLabel}
    >
      <option value="">{currentLabel}</option>
      {versions?.map((item) => (
        <option key={item.version} value={item.version}>v{item.version} · {item.created_at}</option>
      ))}
    </select>
  );
}

function DiffList({
  snapshot,
  current,
  title,
  empty,
}: {
  snapshot: PlanVersionDetail["snapshot"];
  current: TradePlan["input_snapshot"];
  title: string;
  empty: string;
}) {
  const rows = diffRows(snapshot, current);
  return (
    <div>
      <h4 className="text-xs text-muted">{title}</h4>
      {rows.length === 0 ? <p className="mt-1 text-xs text-muted">{empty}</p> : (
        <ul className="mt-1 space-y-1 text-xs">
          {rows.map((row) => <li key={row}>{row}</li>)}
        </ul>
      )}
    </div>
  );
}

function diffRows(snapshot: PlanVersionDetail["snapshot"], current: TradePlan["input_snapshot"]): string[] {
  const rows: string[] = [];
  const left: Partial<CapitalPreferences> = snapshot.capital ?? {};
  const right: Partial<CapitalPreferences> = current?.capital ?? {};
  const capitalKeys = ["available_capital", "available_cash", "max_risk_amount", "max_risk_percent", "max_position_percent", "cost_bps"] as const;
  for (const key of capitalKeys) {
    const before = left[key] ?? null;
    const after = right[key] ?? null;
    if (before !== after) rows.push(`${key}: ${before ?? "—"} → ${after ?? "—"}`);
  }
  const scale = JSON.stringify(snapshot.scale_in_prices ?? []);
  const currentScale = JSON.stringify(current?.scale_in_prices ?? []);
  if (scale !== currentScale) rows.push(`scale-in: ${scale} → ${currentScale}`);
  const take = JSON.stringify(snapshot.take_profit_prices ?? []);
  const currentTake = JSON.stringify(current?.take_profit_prices ?? []);
  if (take !== currentTake) rows.push(`take-profit: ${take} → ${currentTake}`);
  return rows;
}

function planGap(decision: FinalDecision | undefined, plan: TradePlan | null | undefined, t: (key: string) => string): { summary: string; original: string | null } {
  const status = decision?.plan_status;
  const fields = decision?.price_fields ?? {};
  const states = [fields.entry_price, fields.stop_loss, fields.price_target];
  let summary = t("plan.reasonUnknown");
  if (status === "not_applicable") summary = t("plan.notApplicable");
  else if (states.some((state) => state === "unreadable") || status === "parse_failed") summary = t("plan.parseFailed");
  else if (plan?.verified_market?.status === "unavailable" || plan?.calculation_market?.status === "unavailable") summary = t("plan.readFailed");
  else if (states.every((state) => state === "stated_absent")) summary = t("plan.notProvided");
  else if (status === "missing_parameters") summary = t("plan.missingUser");
  else if (status === "ready") summary = t("planState.ready");
  const original = [decision?.plan_reason, decision?.next_step].filter(Boolean).join("\n");
  return { summary, original: original || null };
}

function reasonForState(state: string, t: (key: string) => string): string {
  if (state === "stated_absent") return t("plan.notProvided");
  if (state === "unreadable") return t("plan.parseFailed");
  if (state === "missing") return t("plan.reasonUnknown");
  return t("common.unknown");
}

function Field({ id, label, value, error, onChange, suffix }: { id: string; label: string; value: string; error?: string; onChange: (value: string) => void; suffix?: string }) {
  const errorId = error ? `${id}-error` : undefined;
  return (
    <label className="block text-xs text-muted" htmlFor={id}>
      {label}{suffix ? ` (${suffix})` : ""}
      <Input id={id} className="num mt-1" inputMode="decimal" aria-invalid={Boolean(error)} aria-describedby={errorId} value={value} onChange={(event) => onChange(event.target.value)} />
      {error && <span id={errorId} className="mt-1 block text-danger">{error}</span>}
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="num text-xs">{value}</dd>
    </div>
  );
}

function toDraft(preferences: CapitalPreferences, snapshot: TradePlan["input_snapshot"]): PlanDraft {
  const capital = snapshot?.capital ?? preferences;
  return {
    available_capital: capital.available_capital?.toString() ?? "",
    available_cash: capital.available_cash?.toString() ?? "",
    max_risk_amount: capital.max_risk_amount?.toString() ?? "",
    max_risk_percent: capital.max_risk_percent?.toString() ?? "",
    max_position_percent: capital.max_position_percent?.toString() ?? "",
    cost_bps: String(capital.cost_bps ?? preferences.cost_bps ?? 0),
    scale_in_prices: priceList(snapshot?.scale_in_prices),
    take_profit_prices: priceList(snapshot?.take_profit_prices),
  };
}

function capitalFieldErrors(draft: PlanDraft, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {};
  const checks: [keyof PlanDraft, string, { min?: number; max?: number }][] = [
    ["available_capital", t("plan.account"), { min: 0 }],
    ["available_cash", t("plan.cash"), { min: 0 }],
    ["max_risk_amount", t("plan.riskAmount"), { min: 0 }],
    ["max_risk_percent", t("plan.riskPercent"), { min: 0, max: 100 }],
    ["max_position_percent", t("plan.position"), { min: 0, max: 100 }],
    ["cost_bps", t("plan.cost"), { min: 0, max: 10000 }],
  ];
  for (const [key, label, options] of checks) {
    const error = localizedNumberError(draft[key], label, options, t);
    if (error) errors[key] = error;
  }
  return errors;
}

function priceFieldErrors(draft: PlanDraft, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {};
  const scale = localizedPriceError(draft.scale_in_prices, t);
  const exits = localizedPriceError(draft.take_profit_prices, t);
  if (scale) errors.scale_in_prices = scale;
  if (exits) errors.take_profit_prices = exits;
  return errors;
}

function manualFieldErrors(manual: { entry: string; stop: string; target: string }, t: (key: string) => string): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, label] of [["entry", t("plan.entry")], ["stop", t("plan.stop")], ["target", t("plan.target")]] as const) {
    const error = localizedNumberError(manual[key], label, { min: 0 }, t);
    if (error && manual[key].trim()) errors[key] = error;
  }
  return errors;
}

function localizedNumberError(value: string, label: string, options: { min?: number; max?: number }, t: (key: string) => string): string | null {
  const text = value.trim();
  if (!text) return null;
  const number = Number(text);
  if (!Number.isFinite(number)) return t("field.number").replace("{label}", label);
  if (options.min !== undefined && number < options.min) return t("field.min").replace("{label}", label).replace("{bound}", String(options.min));
  if (options.max !== undefined && number > options.max) return t("field.max").replace("{label}", label).replace("{bound}", String(options.max));
  return null;
}

function localizedPriceError(value: string, t: (key: string) => string): string | null {
  if (!value.trim()) return null;
  for (const part of value.split(",")) {
    const text = part.trim();
    if (!text) continue;
    const number = Number(text);
    if (!Number.isFinite(number) || number <= 0) return t("field.price").replace("{value}", text);
  }
  return null;
}

function parseDraft(draft: PlanDraft, t: (key: string) => string): {
  capital: CapitalPreferences;
  prices: { scale_in_prices: number[]; take_profit_prices: number[] };
  errors: Record<string, string> | null;
} {
  const errors = { ...capitalFieldErrors(draft, t), ...priceFieldErrors(draft, t) };
  return {
    capital: {
      available_capital: parseOptionalNumber(draft.available_capital),
      available_cash: parseOptionalNumber(draft.available_cash),
      max_risk_amount: parseOptionalNumber(draft.max_risk_amount),
      max_risk_percent: parseOptionalNumber(draft.max_risk_percent),
      max_position_percent: parseOptionalNumber(draft.max_position_percent),
      cost_bps: parseOptionalNumber(draft.cost_bps) ?? 0,
    },
    prices: {
      scale_in_prices: parsePriceList(draft.scale_in_prices),
      take_profit_prices: parsePriceList(draft.take_profit_prices),
    },
    errors: Object.keys(errors).length ? errors : null,
  };
}
