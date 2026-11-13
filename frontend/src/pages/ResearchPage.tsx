import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { AgentWorkflow, Panel } from "../components/AgentWorkflow.tsx";
import { PriceChart, type ChartLevel } from "../components/PriceChart.tsx";
import { ReportTabs } from "../components/ReportTabs.tsx";
import { TradePlanPanel } from "../components/TradePlanPanel.tsx";
import { Badge } from "../components/ui/badge.tsx";
import { Button } from "../components/ui/button.tsx";
import { Input, Select } from "../components/ui/input.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs.tsx";
import { useAnalysisStream } from "../hooks/useAnalysisStream.ts";
import { formatNumber, formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { AnalysisRecord, AnalystId, ConfigOptions, MarketChart, RunSettings } from "../types/api.ts";

interface FormState {
  ticker: string;
  analysis_date: string;
  analysts: AnalystId[];
  research_depth: 1 | 3 | 5;
  output_language: "English" | "Chinese";
  llm_provider: string;
  quick_think_llm: string;
  deep_think_llm: string;
  backend_url: string;
}

const ANALYSTS: AnalystId[] = ["market", "social", "news", "fundamentals"];
const ACTIVE = new Set(["queued", "running", "cancel_requested", "cancelling"]);
const RANGES = [
  { id: "1M", bars: 21 },
  { id: "3M", bars: 63 },
  { id: "6M", bars: 126 },
  { id: "1Y", bars: 252 },
  { id: "All", bars: null },
] as const;

export function ResearchPage() {
  const { analysisId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tickerParam = params.get("ticker") ?? "";
  const fromId = params.get("from") ?? "";
  const options = useQuery({
    queryKey: ["options"],
    queryFn: () => api<ConfigOptions>("/api/config/options"),
    staleTime: 60_000,
  });
  const analysis = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => api<AnalysisRecord>(`/api/analyses/${analysisId}`),
    enabled: Boolean(analysisId),
  });
  const template = useQuery({
    queryKey: ["analysis", fromId],
    queryFn: () => api<AnalysisRecord>(`/api/analyses/${fromId}`),
    enabled: !analysisId && Boolean(fromId),
  });
  const active = useQuery({
    queryKey: ["analyses", "active"],
    queryFn: () => api<AnalysisRecord[]>("/api/analyses/active"),
    refetchInterval: 5000,
  });
  const [form, setForm] = useState<FormState | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [rangeBars, setRangeBars] = useState<number | null>(252);
  const [watchMessage, setWatchMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!options.data || form) return;
    setForm(initialForm(options.data, tickerParam));
  }, [form, options.data, tickerParam]);

  useEffect(() => {
    if (!tickerParam) return;
    setForm((current) => (current ? { ...current, ticker: tickerParam } : current));
  }, [tickerParam]);

  useEffect(() => {
    const source = analysis.data ?? (!analysisId ? template.data : undefined);
    if (!source || !options.data) return;
    const saved = formFromSettings(source.settings);
    setForm(options.data.providers.some((provider) => provider.id === saved.llm_provider)
      ? saved
      : selectProvider(saved, options.data, options.data.default_provider));
  }, [analysis.data?.id, analysisId, options.data, template.data?.id]);

  const running = analysis.data ? ACTIVE.has(analysis.data.status) : false;
  useAnalysisStream(analysisId, running);

  const chartTicker = analysis.data?.ticker || form?.ticker || "";
  const chartDate = analysis.data?.analysis_date || form?.analysis_date || options.data?.today || "";
  const market = useQuery({
    queryKey: ["market", chartTicker, chartDate],
    queryFn: () => api<MarketChart>(`/api/market/${encodeURIComponent(chartTicker)}?as_of=${chartDate}`),
    enabled: Boolean(chartTicker && chartDate),
  });

  const start = useMutation({
    mutationFn: (body: FormState) =>
      api<AnalysisRecord>("/api/analyses", {
        method: "POST",
        body: JSON.stringify({
          ...body,
          ticker: body.ticker.trim(),
          backend_url: body.backend_url.trim() || null,
        }),
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["analyses"] });
      navigate(`/research/${result.id}`);
    },
  });
  const cancel = useMutation({
    mutationFn: () => api<AnalysisRecord>(`/api/analyses/${analysisId}/cancel`, { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["analysis", analysisId] });
    },
  });
  const addWatch = useMutation({
    mutationFn: (ticker: string) => api<{ ticker: string }>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
    onSuccess: async (result) => {
      setWatchMessage(`${result.ticker} added`);
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });

  const provider = options.data?.providers.find((item) => item.id === form?.llm_provider);
  const busy = start.isPending || (active.data ?? []).some((row) => ACTIVE.has(row.status));
  const levels = useMemo(() => levelsFrom(analysis.data?.trade_plan), [analysis.data?.trade_plan]);
  const record = analysis.data;
  const latest = record?.activity?.[record.activity.length - 1];
  const depthLabel = options.data?.depths.find((item) => item.id === form?.research_depth)?.label ?? "Shallow";

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium">{record?.ticker ?? form?.ticker ?? "Research"}</h1>
          <p className="mt-1 text-sm text-[#4d5d6d]">
            {record?.analysis_date ?? form?.analysis_date ?? "Choose a date"} · {record ? record.status.replaceAll("_", " ") : "Not started"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {record && ACTIVE.has(record.status) && (
            <Button type="button" variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {record.status === "cancelling" || record.status === "cancel_requested" ? "Stopping" : "Cancel"}
            </Button>
          )}
          <Button type="button" variant="outline" onClick={() => navigate("/research")}>New research</Button>
        </div>
      </header>
      {record?.settings.llm_provider === "chatgpt" && (
        <p className="text-sm text-[#8a5a00]">
          This saved run used ChatGPT subscription settings. A new run uses the provider selected below and does not change the saved run.
        </p>
      )}
      {fromId && !analysisId && (
        <p className="text-sm text-[#4d5d6d]">Settings were copied from a saved run. Starting research creates a new record.</p>
      )}
      {record && !ACTIVE.has(record.status) && record.status !== "completed" && (
        <Panel title="This run stopped">
          <p className="text-sm text-[#b42334]">{record.error_code}: {record.error}</p>
          <p className="mt-2 text-sm text-[#4d5d6d]">
            Kept sections: {record.reports && Object.keys(record.reports).length ? Object.keys(record.reports).join(", ") : "none"}.
            {" "}You can read them below or start a new research run. This record is not overwritten.
          </p>
        </Panel>
      )}
      <div className="grid gap-4 xl:grid-cols-12">
        <div className="xl:col-span-3">
          <Panel title="Run setup">
            {options.isError && <p role="alert" className="text-sm text-[#b42334]">Configuration could not be loaded: {options.error.message}</p>}
            {analysis.isError && <p role="alert" className="text-sm text-[#b42334]">Research could not be loaded: {analysis.error.message}</p>}
            {!options.isError && (!form || !options.data) ? (
              <p className="text-sm text-[#4d5d6d]">Loading configuration.</p>
            ) : form && options.data ? (
              <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); start.mutate(form); }}>
                <Label text="Ticker">
                  <Input value={form.ticker} onChange={(event) => setForm({ ...form, ticker: event.target.value.toUpperCase() })} required />
                </Label>
                <Label text="Analysis date">
                  <Input type="date" max={options.data.today} value={form.analysis_date} onChange={(event) => setForm({ ...form, analysis_date: event.target.value })} required />
                </Label>
                <fieldset>
                  <legend className="mb-1 text-xs text-[#4d5d6d]">Analysts</legend>
                  <div className="space-y-1">
                    {options.data.analysts.map((analyst) => (
                      <label key={analyst.id} className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={form.analysts.includes(analyst.id)} onChange={() => setForm({ ...form, analysts: toggleAnalyst(form.analysts, analyst.id) })} />
                        {analyst.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <Label text="Research depth">
                  <Select value={String(form.research_depth)} onChange={(event) => setForm({ ...form, research_depth: Number(event.target.value) as FormState["research_depth"] })}>
                    {options.data.depths.map((depth) => (
                      <option key={depth.id} value={depth.id}>{depth.label}</option>
                    ))}
                  </Select>
                </Label>
                <p className="text-xs leading-5 text-[#4d5d6d]">
                  {depthLabel} uses {form.analysts.length} analyst{form.analysts.length === 1 ? "" : "s"} on {form.quick_think_llm || "the quick model"} and {form.deep_think_llm || "the deep model"}. Deeper research makes more model calls. There is a call-count guard, not a verified dollar cap.
                </p>
                <button type="button" className="text-xs text-[#1a56a8]" onClick={() => setAdvanced((value) => !value)}>
                  {advanced ? "Hide model settings" : "Model settings"}
                </button>
                {advanced && (
                  <div className="space-y-3">
                    <Label text="Language">
                      <Select value={form.output_language} onChange={(event) => setForm({ ...form, output_language: event.target.value as FormState["output_language"] })}>
                        {options.data.languages.map((language) => (
                          <option key={language} value={language}>{language}</option>
                        ))}
                      </Select>
                    </Label>
                    <Label text="Model provider">
                      <Select value={form.llm_provider} onChange={(event) => setForm(selectProvider(form, options.data, event.target.value))}>
                        {options.data.providers.map((item) => (
                          <option key={item.id} value={item.id}>{item.label}</option>
                        ))}
                      </Select>
                    </Label>
                    {provider?.auth_message && <p className="text-xs text-[#8a5a00]">{provider.auth_message}</p>}
                    <ModelField label="Quick model" value={form.quick_think_llm} choices={provider?.models.quick ?? []} onChange={(value) => setForm({ ...form, quick_think_llm: value })} />
                    <ModelField label="Deep model" value={form.deep_think_llm} choices={provider?.models.deep ?? []} onChange={(value) => setForm({ ...form, deep_think_llm: value })} />
                    {provider?.requires_url && (
                      <Label text="Endpoint URL">
                        <Input value={form.backend_url} onChange={(event) => setForm({ ...form, backend_url: event.target.value })} placeholder={provider.default_url ?? "https://"} />
                      </Label>
                    )}
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button type="submit" disabled={busy || form.analysts.length === 0}>
                    {busy ? "Analysis running" : "Run analysis"}
                  </Button>
                  <Button type="button" variant="outline" disabled={!form.ticker.trim() || addWatch.isPending} onClick={() => addWatch.mutate(form.ticker.trim())}>
                    Watch
                  </Button>
                </div>
                {start.isError && <p className="text-xs text-[#b42334]">{start.error.message}</p>}
                {cancel.isError && <p className="text-xs text-[#b42334]">{cancel.error.message}</p>}
                {addWatch.isError && <p className="text-xs text-[#b42334]">{addWatch.error.message}</p>}
                {watchMessage && <p className="text-xs text-[#4d5d6d]">{watchMessage}</p>}
              </form>
            ) : null}
          </Panel>
        </div>
        <div className="xl:col-span-9">
          <Tabs defaultValue={record?.status === "completed" ? "summary" : "log"}>
            <TabsList>
              <TabsTrigger value="summary">Summary</TabsTrigger>
              <TabsTrigger value="chart">Chart and evidence</TabsTrigger>
              <TabsTrigger value="plan">Trade plan</TabsTrigger>
              <TabsTrigger value="report">Full report</TabsTrigger>
              <TabsTrigger value="log">Run log</TabsTrigger>
            </TabsList>
            <TabsContent value="summary">
              <Panel title="Conclusion">
                {running && (
                  <p className="text-sm text-[#4d5d6d]">
                    Phase: {record?.phase.replaceAll("_", " ")}. Latest: {latest?.message ?? "Waiting for the next update."} There is no percentage completion.
                  </p>
                )}
                {!record && <p className="text-sm text-[#4d5d6d]">Run an analysis to see a conclusion. Missing prices stay missing.</p>}
                {record?.trade_plan && (
                  <div className="space-y-2 text-sm">
                    <p>{record.trade_plan.explanation}</p>
                    <p className="text-xs text-[#4d5d6d]">
                      Rating {record.rating === "REVIEW" ? "not readable" : record.rating ?? "not available"} · {record.analysis_date} · {record.status.replaceAll("_", " ")}
                    </p>
                    <ul className="space-y-1 text-xs">
                      {record.trade_plan.evidence.map((item) => (
                        <li key={item.label}>{item.label}: {item.status}{item.detail ? ` · ${item.detail}` : ""}</li>
                      ))}
                    </ul>
                    <ToolNotes sources={record.data_sources} />
                  </div>
                )}
                {record && !record.trade_plan && !running && <p className="text-sm text-[#4d5d6d]">This run has no calculated plan.</p>}
              </Panel>
            </TabsContent>
            <TabsContent value="chart">
              <Panel title={chartTicker ? `${chartTicker} market data` : "Market data"} action={<Badge>{market.isError ? "Unavailable" : market.data ? market.data.session ?? "Yahoo" : "Waiting"}</Badge>}>
                {market.isLoading && <p className="text-sm text-[#4d5d6d]">Loading Yahoo prices.</p>}
                {market.error && <p className="text-sm text-[#b42334]">Market data failed. {market.error.message} No simulated prices were substituted.</p>}
                {market.data && (
                  <>
                    <div className="mb-3 flex flex-wrap items-end justify-between gap-3 text-sm">
                      <div>
                        <div className="font-mono text-2xl">{formatNumber(market.data.reference_price)}</div>
                        <p className="max-w-xl text-xs leading-5 text-[#4d5d6d]">
                          Bar {market.data.bar_date} · session {market.data.session ?? "unknown"}
                          {market.data.bar_complete === false ? " · not a closed daily bar" : market.data.bar_complete ? " · closed daily bar" : " · session unknown"}.
                          {" "}Download started {formatWhen(market.data.download_started_at)} · downloaded {formatWhen(market.data.fetched_at)} · response {formatWhen(market.data.response_at)}.
                          {" "}Currency {market.data.currency ?? "unknown"} · timezone {market.data.timezone ?? "unknown"} · cache {market.data.cache_status ?? "unknown"}.
                        </p>
                        {market.data.session_note && <p className="text-xs text-[#8a5a00]">{market.data.session_note}</p>}
                      </div>
                      <div className="flex flex-wrap gap-2 text-xs text-[#4d5d6d]">
                        {RANGES.map((item) => (
                          <button key={item.id} type="button" className={rangeBars === item.bars ? "text-[#1a2330]" : ""} onClick={() => setRangeBars(item.bars)}>
                            {item.id}
                          </button>
                        ))}
                        <label className="flex items-center gap-1"><input type="checkbox" checked={showRsi} onChange={() => setShowRsi((value) => !value)} /> RSI</label>
                        <label className="flex items-center gap-1"><input type="checkbox" checked={showMacd} onChange={() => setShowMacd((value) => !value)} /> MACD</label>
                      </div>
                    </div>
                    <PriceChart candles={market.data.candles} levels={levels} showRsi={showRsi} showMacd={showMacd} rangeBars={rangeBars} />
                    <p className="mt-2 text-[11px] leading-5 text-[#6b7c8d]">
                      Solid lines are indicators from Yahoo closes. Dashed lines are research hypotheses, not orders or fills.
                      {" "}{market.data.indicator_note}
                      {market.data.indicators_error ? ` Indicator warning: ${market.data.indicators_error}` : ""}
                    </p>
                  </>
                )}
              </Panel>
            </TabsContent>
            <TabsContent value="plan">
              <Panel title="Trade plan">
                <TradePlanPanel analysisId={analysisId} ticker={record?.ticker} plan={record?.trade_plan} />
              </Panel>
            </TabsContent>
            <TabsContent value="report">
              <Panel title="Research reports" action={<Badge className="border-[#c4a15a] text-[#8a5a00]">Generated</Badge>}>
                <ReportTabs reports={record?.reports} />
                {record?.html_report_path && (
                  <a className="mt-3 inline-block text-sm text-[#1a56a8]" href={`/api/analyses/${record.id}/report`}>Open HTML report</a>
                )}
              </Panel>
            </TabsContent>
            <TabsContent value="log">
              <Panel title="Run log">
                <AgentWorkflow phase={record?.phase ?? "queued"} agentStatus={record?.agent_status ?? {}} activity={record?.activity ?? []} />
                {record?.error && <p className="mt-3 text-sm text-[#b42334]">{record.error_code}: {record.error}</p>}
                <ToolNotes sources={record?.data_sources} />
              </Panel>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function ToolNotes({ sources }: { sources: AnalysisRecord["data_sources"] | undefined }) {
  if (!sources) return null;
  const record = sources as { memory_error?: string | null; report_error?: string | null; estimated_cost?: { status?: string; reason?: string }; usage?: { status?: string } };
  const notes = [record.memory_error, record.report_error].filter(Boolean);
  return (
    <div className="mt-3 space-y-1 text-xs text-[#4d5d6d]">
      <p>Estimated cost: {record.estimated_cost?.status ?? "unknown"}. {record.estimated_cost?.reason ?? "Usage is shown only when the provider reports it."}</p>
      <p>Usage: {record.usage && record.usage.status !== "unknown" ? "recorded from the provider" : "unknown"}.</p>
      {notes.map((note) => <p key={note}>Tool failure: {note}</p>)}
      <p>A completed status does not mean every data tool succeeded.</p>
    </div>
  );
}

function Label({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-[#4d5d6d]">
      {text}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function ModelField({ label, value, choices, onChange }: { label: string; value: string; choices: { id: string; label: string }[]; onChange: (value: string) => void }) {
  return (
    <Label text={label}>
      {choices.length > 0 && (
        <Select className="mb-1" value={choices.some((choice) => choice.id === value) ? value : ""} onChange={(event) => onChange(event.target.value)}>
          <option value="">Choose or type</option>
          {choices.map((choice) => (
            <option key={choice.id} value={choice.id}>{choice.label}</option>
          ))}
        </Select>
      )}
      <Input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Model ID" required />
    </Label>
  );
}

function initialForm(options: ConfigOptions, ticker: string): FormState {
  const provider = options.providers.find((item) => item.id === options.default_provider) ?? options.providers[0];
  return {
    ticker: ticker || "",
    analysis_date: options.today,
    analysts: [...ANALYSTS],
    research_depth: 1,
    output_language: "English",
    llm_provider: provider?.id ?? "openai",
    quick_think_llm: provider?.models.quick[0]?.id ?? "",
    deep_think_llm: provider?.models.deep[0]?.id ?? "",
    backend_url: provider?.requires_url ? provider.default_url ?? "" : "",
  };
}

function formFromSettings(settings: RunSettings): FormState {
  return {
    ticker: settings.ticker,
    analysis_date: settings.analysis_date,
    analysts: settings.analysts,
    research_depth: settings.research_depth,
    output_language: settings.output_language,
    llm_provider: settings.llm_provider,
    quick_think_llm: settings.quick_think_llm,
    deep_think_llm: settings.deep_think_llm,
    backend_url: settings.backend_url ?? "",
  };
}

function selectProvider(form: FormState, options: ConfigOptions | undefined, providerId: string): FormState {
  const provider = options?.providers.find((item) => item.id === providerId);
  return {
    ...form,
    llm_provider: providerId,
    quick_think_llm: provider?.models.quick[0]?.id ?? "",
    deep_think_llm: provider?.models.deep[0]?.id ?? "",
    backend_url: provider?.requires_url ? provider.default_url ?? "" : "",
  };
}

function toggleAnalyst(current: AnalystId[], analyst: AnalystId): AnalystId[] {
  return current.includes(analyst) ? current.filter((item) => item !== analyst) : [...current, analyst];
}

function levelsFrom(plan: AnalysisRecord["trade_plan"]): ChartLevel[] {
  if (!plan) return [];
  const levels: ChartLevel[] = [];
  if (plan.hypotheses.entry_price !== null) levels.push({ price: plan.hypotheses.entry_price, title: "Hypothesis entry", color: "#8a5a00" });
  if (plan.hypotheses.stop_loss !== null) levels.push({ price: plan.hypotheses.stop_loss, title: "Hypothesis stop", color: "#c4233c" });
  if (plan.hypotheses.price_target !== null) levels.push({ price: plan.hypotheses.price_target, title: "Hypothesis target", color: "#0c7a43" });
  return levels;
}
