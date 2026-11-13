import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { formatNumber, formatShares, numberError, parseOptionalNumber, parsePriceList, priceList, priceListError } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { CapitalPreferences, PositionSizeResult, TradePlan } from "../types/api.ts";
import { Badge } from "./ui/badge.tsx";
import { Button } from "./ui/button.tsx";
import { Input } from "./ui/input.tsx";

const EMPTY_CAPITAL: CapitalPreferences = {
  available_capital: null,
  available_cash: null,
  max_risk_amount: null,
  max_risk_percent: null,
  max_position_percent: null,
  cost_bps: 0,
};

interface Draft {
  available_capital: string;
  available_cash: string;
  max_risk_amount: string;
  max_risk_percent: string;
  max_position_percent: string;
  cost_bps: string;
  scale_in_prices: string;
  take_profit_prices: string;
}

export function TradePlanPanel({
  analysisId,
  ticker,
  plan,
}: {
  analysisId?: string;
  ticker?: string;
  plan: TradePlan | null | undefined;
}) {
  const queryClient = useQueryClient();
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api<CapitalPreferences>("/api/preferences"),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [manual, setManual] = useState({ entry: "", stop: "", target: "", action: "Buy" });
  const [preview, setPreview] = useState<PositionSizeResult | null>(null);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    setDraft(null);
    setPreview(null);
    setStale(false);
    setManual({ entry: "", stop: "", target: "", action: "Buy" });
  }, [analysisId]);

  useEffect(() => {
    if (!preferences.data || draft) return;
    setDraft(toDraft(preferences.data, plan?.input_snapshot));
  }, [analysisId, draft, plan?.input_snapshot, preferences.data]);

  const save = useMutation({
    mutationFn: async (next: Draft) => {
      const parsed = parseDraft(next);
      if (parsed.errors) {
        throw new Error("Fix the highlighted fields before saving.");
      }
      if (!analysisId) {
        return api<CapitalPreferences>("/api/preferences", { method: "PUT", body: JSON.stringify(parsed.capital) });
      }
      return api<TradePlan>(`/api/analyses/${analysisId}/trade-plan`, {
        method: "POST",
        body: JSON.stringify({ ...parsed.capital, ...parsed.prices }),
      });
    },
    onSuccess: async () => {
      setStale(false);
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
      if (analysisId) await queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] });
    },
  });

  const calculate = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<PositionSizeResult>("/api/position-size", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: setPreview,
  });

  function edit(key: keyof Draft, value: string) {
    setDraft((current) => ({ ...(current ?? toDraft(preferences.data ?? EMPTY_CAPITAL, null)), [key]: value }));
    if (plan) setStale(true);
    setPreview(null);
  }

  const capitalErrors = draft ? capitalFieldErrors(draft) : {};
  const priceErrors = draft ? priceFieldErrors(draft) : {};
  const manualErrors = manualFieldErrors(manual);

  return (
    <div className="space-y-4">
      <p className="text-xs leading-5 text-[#4d5d6d]">
        Verified prices come from Yahoo Finance. Entry, stop, and target are research hypotheses only when a labeled
        field parsed as one positive number. Share counts are calculated in Python. No order is sent.
      </p>
      {plan ? <PlanView plan={plan} stale={stale} /> : <p className="text-sm text-[#4d5d6d]">A trade plan is attached when an analysis finishes, or after you recalculate.</p>}
      <form
        className="grid gap-3 border-t border-[#d5dee6] pt-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft) return;
          const errors = { ...capitalFieldErrors(draft), ...priceFieldErrors(draft) };
          if (Object.keys(errors).length) return;
          save.mutate(draft);
        }}
      >
        <h3 className="sm:col-span-2 text-xs tracking-wide text-[#6b7c8d] uppercase">Capital inputs</h3>
        <p className="sm:col-span-2 text-xs text-[#4d5d6d]">These capital fields are shared. Price ladders below belong only to {ticker ?? "this research"}.</p>
        <Field label="Available capital" value={draft?.available_capital ?? ""} error={capitalErrors.available_capital} onChange={(value) => edit("available_capital", value)} />
        <Field label="Available cash" value={draft?.available_cash ?? ""} error={capitalErrors.available_cash} onChange={(value) => edit("available_cash", value)} />
        <Field label="Max risk $" value={draft?.max_risk_amount ?? ""} error={capitalErrors.max_risk_amount} onChange={(value) => edit("max_risk_amount", value)} />
        <Field label="Max risk %" value={draft?.max_risk_percent ?? ""} error={capitalErrors.max_risk_percent} onChange={(value) => edit("max_risk_percent", value)} />
        <Field label="Max position %" value={draft?.max_position_percent ?? ""} error={capitalErrors.max_position_percent} onChange={(value) => edit("max_position_percent", value)} />
        <Field label="Cost (bps)" value={draft?.cost_bps ?? "0"} error={capitalErrors.cost_bps} onChange={(value) => edit("cost_bps", value)} />
        <p className="sm:col-span-2 text-xs text-[#4d5d6d]">If both a risk amount and a risk percent are filled, the tighter budget is used. Neither value is discarded.</p>
        <label className="sm:col-span-2 block text-xs text-[#4d5d6d]">
          Scale-in prices for this research
          <Input className="mt-1" value={draft?.scale_in_prices ?? ""} onChange={(event) => edit("scale_in_prices", event.target.value)} placeholder="Optional, comma separated" />
          {priceErrors.scale_in_prices && <span className="mt-1 block text-[#b42334]">{priceErrors.scale_in_prices}</span>}
        </label>
        <label className="sm:col-span-2 block text-xs text-[#4d5d6d]">
          Take-profit prices for this research
          <Input className="mt-1" value={draft?.take_profit_prices ?? ""} onChange={(event) => edit("take_profit_prices", event.target.value)} placeholder="Optional, comma separated" />
          {priceErrors.take_profit_prices && <span className="mt-1 block text-[#b42334]">{priceErrors.take_profit_prices}</span>}
        </label>
        <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!draft || save.isPending}>
            {analysisId ? "Save and recalculate" : "Save capital inputs"}
          </Button>
          {stale && <span className="text-xs text-[#8a5a00]">Draft changed. Results are waiting to be recalculated.</span>}
          {plan?.plan_version ? <span className="text-xs text-[#6b7c8d]">Saved plan version {plan.plan_version}</span> : null}
          {save.isError && <span className="text-xs text-[#b42334]">{save.error.message}</span>}
        </div>
      </form>
      <form
        className="grid gap-3 border-t border-[#d5dee6] pt-3 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!draft) return;
          const errors = { ...capitalFieldErrors(draft), ...manualFieldErrors(manual) };
          if (Object.values(errors).some(Boolean)) return;
          const capital = parseDraft(draft);
          if (capital.errors) return;
          setPreview(null);
          calculate.mutate({
            ...capital.capital,
            ...capital.prices,
            entry_price: parseOptionalNumber(manual.entry),
            stop_loss: parseOptionalNumber(manual.stop),
            price_target: parseOptionalNumber(manual.target),
            action: manual.action || null,
          });
        }}
      >
        <h3 className="sm:col-span-4 text-xs tracking-wide text-[#6b7c8d] uppercase">Manual calculator</h3>
        <p className="sm:col-span-4 text-xs text-[#4d5d6d]">These prices are typed here. They are not research hypotheses and they are not saved as this research plan.</p>
        <Field label="Entry" value={manual.entry} error={manualErrors.entry} onChange={(value) => { setManual({ ...manual, entry: value }); setPreview(null); }} />
        <Field label="Stop" value={manual.stop} error={manualErrors.stop} onChange={(value) => { setManual({ ...manual, stop: value }); setPreview(null); }} />
        <Field label="Target" value={manual.target} error={manualErrors.target} onChange={(value) => { setManual({ ...manual, target: value }); setPreview(null); }} />
        <label className="block text-xs text-[#4d5d6d]">
          Action
          <Input className="mt-1" value={manual.action} onChange={(event) => { setManual({ ...manual, action: event.target.value }); setPreview(null); }} />
        </label>
        <div className="sm:col-span-4">
          <Button type="submit" variant="outline" disabled={calculate.isPending}>Calculate</Button>
        </div>
        {preview && (
          <div className="sm:col-span-4 text-sm">
            <Badge>Manual preview, not saved</Badge>
            <LevelTable title="Manual entries" rows={preview.limit_entries} />
            <Metric label="Shares" value={formatShares(preview.sizing.shares)} />
            <Metric label="Planned loss" value={formatNumber(preview.sizing.planned_loss)} />
            <p className="mt-1 text-xs text-[#4d5d6d]">{preview.sizing.reason ?? "Calculated from the typed prices and capital inputs."}</p>
          </div>
        )}
        {calculate.isError && <p className="sm:col-span-4 text-xs text-[#b42334]">{calculate.error.message}</p>}
      </form>
    </div>
  );
}

function PlanView({ plan, stale }: { plan: TradePlan; stale: boolean }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap gap-2">
        <Badge>{plan.plan_version ? `Saved version ${plan.plan_version}` : "Saved plan"}</Badge>
        {stale && <Badge className="border-[#c4a15a] text-[#8a5a00]">Waiting to recalculate</Badge>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Block title="Verified market" tone="verified">
          <Metric label="Source" value={plan.verified_market.source} />
          <Metric label="Close" value={formatNumber(plan.verified_market.price)} />
          <Metric label="Bar date" value={plan.verified_market.bar_date ?? "Unknown"} />
          <Metric label="Fetched" value={plan.verified_market.fetched_at ?? "Unknown"} />
          {plan.verified_market.error && <p className="mt-1 text-xs text-[#b42334]">{plan.verified_market.error}</p>}
        </Block>
        <Block title="Research hypotheses" tone="hypothesis">
          <Metric label="Action" value={plan.hypotheses.action ?? "Unavailable"} />
          <Metric label="Rating" value={plan.hypotheses.rating ?? "Unavailable"} />
          <Metric label="Entry" value={formatNumber(plan.hypotheses.entry_price)} />
          <Metric label="Stop" value={formatNumber(plan.hypotheses.stop_loss)} />
          <Metric label="Target" value={formatNumber(plan.hypotheses.price_target)} />
          {plan.hypotheses.entry_price === null && <p className="mt-1 text-xs text-[#8a5a00]">No single labeled entry price was found, so none was invented.</p>}
        </Block>
      </div>
      <Block title="Calculated size" tone="calculated">
        <Metric label="Shares" value={formatShares(plan.sizing.shares)} />
        <Metric label="Planned loss" value={formatNumber(plan.sizing.planned_loss)} />
        <Metric label="Capital used" value={formatNumber(plan.sizing.capital_used)} />
        <Metric label="Cash left" value={formatNumber(plan.sizing.remaining_cash)} />
        <Metric label="Risk / reward" value={plan.sizing.risk_reward === null ? "Unavailable" : formatNumber(plan.sizing.risk_reward, 2)} />
        <Metric label="Binding limit" value={plan.sizing.binding_constraint.join(", ") || "Unavailable"} />
        {plan.sizing.reason && <p className="mt-2 text-xs text-[#8a5a00]">{plan.sizing.reason}</p>}
        <p className="mt-2 text-xs leading-5 text-[#4d5d6d]">{plan.explanation}</p>
      </Block>
      <LevelTable title="Limit entries" rows={plan.limit_entries} />
      <LevelTable title="Exits" rows={plan.exits} />
      <div>
        <div className="text-xs text-[#4d5d6d]">Invalidation</div>
        <p className="mt-1">{plan.invalidation.text ?? plan.invalidation.reason ?? "Unavailable"}</p>
      </div>
      <ul className="space-y-1 text-xs text-[#4d5d6d]">
        {plan.assumptions.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function LevelTable({ title, rows }: { title: string; rows: TradePlan["limit_entries"] }) {
  const shares = rows.reduce((sum, row) => sum + (row.shares ?? 0), 0);
  const notion = rows.reduce((sum, row) => sum + (row.shares ?? 0) * row.price, 0);
  const average = shares > 0 ? notion / shares : null;
  return (
    <div>
      <div className="text-xs text-[#4d5d6d]">{title}</div>
      {rows.length === 0 ? (
        <p className="mt-1 text-sm text-[#4d5d6d]">No price was supplied, so no level was created.</p>
      ) : (
        <div className="mt-1 overflow-x-auto">
          <table className="w-full min-w-[420px] text-left font-mono text-xs">
            <thead className="text-[#6b7c8d]">
              <tr>
                <th className="py-1 pr-3 font-medium">Price</th>
                <th className="py-1 pr-3 font-medium">Shares</th>
                <th className="py-1 pr-3 font-medium">Amount</th>
                <th className="py-1 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.source}-${row.price}`} className="border-t border-[#d5dee6]">
                  <td className="py-1 pr-3">{formatNumber(row.price)}</td>
                  <td className="py-1 pr-3">{row.shares === null ? "Unavailable" : formatShares(row.shares)}</td>
                  <td className="py-1 pr-3">{row.shares === null ? "Unavailable" : formatNumber(row.price * row.shares)}</td>
                  <td className="py-1">{row.source.replaceAll("_", " ")}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-[#d5dee6]">
                <td className="py-1 pr-3">Avg {average === null ? "Unavailable" : formatNumber(average)}</td>
                <td className="py-1 pr-3">{shares || "Unavailable"}</td>
                <td className="py-1 pr-3">{shares ? formatNumber(notion) : "Unavailable"}</td>
                <td className="py-1">Before fees</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}

function Block({ title, tone, children }: { title: string; tone: "verified" | "hypothesis" | "calculated"; children: ReactNode }) {
  const badge =
    tone === "verified" ? "border-[#1f6b4a] text-[#0c7a43]" : tone === "hypothesis" ? "border-[#c4a15a] text-[#8a5a00]" : "border-[#b7c4d0] text-[#4d5d6d]";
  return (
    <div className="rounded-md border border-[#d5dee6] p-3">
      <Badge className={badge}>{title}</Badge>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <span className="text-xs text-[#4d5d6d]">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}

function Field({ label, value, error, onChange }: { label: string; value: string; error?: string; onChange: (value: string) => void }) {
  return (
    <label className="block text-xs text-[#4d5d6d]">
      {label}
      <Input className="mt-1 font-mono" inputMode="decimal" aria-invalid={Boolean(error)} value={value} onChange={(event) => onChange(event.target.value)} />
      {error && <span className="mt-1 block text-[#b42334]">{error}</span>}
    </label>
  );
}

function toDraft(preferences: CapitalPreferences, snapshot: TradePlan["input_snapshot"]): Draft {
  return {
    available_capital: preferences.available_capital?.toString() ?? "",
    available_cash: preferences.available_cash?.toString() ?? "",
    max_risk_amount: preferences.max_risk_amount?.toString() ?? "",
    max_risk_percent: preferences.max_risk_percent?.toString() ?? "",
    max_position_percent: preferences.max_position_percent?.toString() ?? "",
    cost_bps: String(preferences.cost_bps ?? 0),
    scale_in_prices: priceList(snapshot?.scale_in_prices),
    take_profit_prices: priceList(snapshot?.take_profit_prices),
  };
}

function capitalFieldErrors(draft: Draft): Record<string, string> {
  const errors: Record<string, string> = {};
  const checks: [keyof Draft, string, { min?: number; max?: number }][] = [
    ["available_capital", "Available capital", { min: 0 }],
    ["available_cash", "Available cash", { min: 0 }],
    ["max_risk_amount", "Max risk $", { min: 0 }],
    ["max_risk_percent", "Max risk %", { min: 0, max: 100 }],
    ["max_position_percent", "Max position %", { min: 0, max: 100 }],
    ["cost_bps", "Cost", { min: 0, max: 10000 }],
  ];
  for (const [key, label, options] of checks) {
    const error = numberError(draft[key], label, options);
    if (error) errors[key] = error;
  }
  return errors;
}

function priceFieldErrors(draft: Draft): Record<string, string> {
  const errors: Record<string, string> = {};
  const scale = priceListError(draft.scale_in_prices);
  const exits = priceListError(draft.take_profit_prices);
  if (scale) errors.scale_in_prices = scale;
  if (exits) errors.take_profit_prices = exits;
  return errors;
}

function manualFieldErrors(manual: { entry: string; stop: string; target: string }): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, label] of [["entry", "Entry"], ["stop", "Stop"], ["target", "Target"]] as const) {
    const error = numberError(manual[key], label, { min: 0 });
    if (error && manual[key].trim()) errors[key] = error;
  }
  return errors;
}

function parseDraft(draft: Draft): {
  capital: CapitalPreferences;
  prices: { scale_in_prices: number[]; take_profit_prices: number[] };
  errors: Record<string, string> | null;
} {
  const errors = { ...capitalFieldErrors(draft), ...priceFieldErrors(draft) };
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
