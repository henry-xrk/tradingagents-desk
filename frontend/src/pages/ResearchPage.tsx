import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState, useSyncExternalStore } from "react";
import { useBlocker, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { AgentWorkflow, Panel } from "../components/AgentWorkflow.tsx";
import { Dialog } from "../components/Dialog.tsx";
import { PriceChart, type ChartLevel } from "../components/PriceChart.tsx";
import { ReportTabs } from "../components/ReportTabs.tsx";
import { ResearchSetup } from "../components/ResearchSetup.tsx";
import { RatingMark } from "../components/StatusText.tsx";
import { TradePlanPanel } from "../components/TradePlanPanel.tsx";
import { Button } from "../components/ui/button.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs.tsx";
import { useAnalysisStream } from "../hooks/useAnalysisStream.ts";
import { useLocale } from "../i18n.tsx";
import { readSession, sessionDirty, sessionKey, subscribePlanSessions, discardSession } from "../lib/planSession.ts";
import { formForRoute, researchMode, routeIdentity, type ResearchFormState } from "../lib/researchForm.ts";
import { formatNumber, formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { AnalysisRecord, ConfigOptions, MarketChart } from "../types/api.ts";

const ACTIVE = new Set(["queued", "running", "cancel_requested", "cancelling"]);
const RANGES = [
  { id: "1M", bars: 21 },
  { id: "3M", bars: 63 },
  { id: "6M", bars: 126 },
  { id: "1Y", bars: 252 },
  { id: "All", bars: null },
] as const;

export function ResearchPage() {
  const { t, locale } = useLocale();
  const { analysisId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tickerParam = params.get("ticker") ?? "";
  const fromId = params.get("from") ?? "";
  const mode = researchMode(analysisId, fromId);
  const identity = routeIdentity(mode, analysisId, fromId, tickerParam);
  const options = useQuery({
    queryKey: ["options"],
    queryFn: ({ signal }) => api<ConfigOptions>("/api/config/options", { signal }),
    staleTime: 60_000,
  });
  const analysis = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: ({ signal }) => api<AnalysisRecord>(`/api/analyses/${analysisId}`, { signal }),
    enabled: Boolean(analysisId),
  });
  const template = useQuery({
    queryKey: ["analysis", fromId],
    queryFn: ({ signal }) => api<AnalysisRecord>(`/api/analyses/${fromId}`, { signal }),
    enabled: !analysisId && Boolean(fromId),
  });
  const active = useQuery({
    queryKey: ["analyses", "active"],
    queryFn: ({ signal }) => api<AnalysisRecord[]>("/api/analyses/active", { signal }),
    refetchInterval: 5000,
  });
  const [form, setForm] = useState<ResearchFormState | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [appliedIdentity, setAppliedIdentity] = useState("");
  const [setupOpen, setSetupOpen] = useState(false);
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [rangeBars, setRangeBars] = useState<number | null>(252);
  const [watchMessage, setWatchMessage] = useState<string | null>(null);
  const [tab, setTab] = useState("summary");
  const [tabFor, setTabFor] = useState(analysisId ?? "");
  const setupButton = useRef<HTMLButtonElement>(null);
  const leaving = useRef(false);
  const source = mode === "open" ? analysis.data : mode === "copy" ? template.data : undefined;
  const ready = Boolean(options.data) && (mode === "new" || Boolean(source));
  if (ready && options.data && appliedIdentity !== identity) {
    setAppliedIdentity(identity);
    setForm(formForRoute({ mode, options: options.data, ticker: tickerParam, saved: source?.settings }));
    if (mode === "new") setAdvanced(false);
  }
  if ((analysisId ?? "") !== tabFor) {
    setTabFor(analysisId ?? "");
    setTab("summary");
  }

  const key = sessionKey(analysisId);
  const planSession = useSyncExternalStore(subscribePlanSessions, () => readSession(key), () => readSession(key));
  const blocker = useBlocker(sessionDirty(planSession));
  const running = analysis.data ? ACTIVE.has(analysis.data.status) : false;
  useAnalysisStream(analysisId, running);

  const chartTicker = analysis.data?.ticker || form?.ticker || "";
  const chartDate = analysis.data?.analysis_date || form?.analysis_date || options.data?.today || "";
  const market = useQuery({
    queryKey: ["market", chartTicker, chartDate],
    queryFn: ({ signal }) => api<MarketChart>(`/api/market/${encodeURIComponent(chartTicker)}?as_of=${chartDate}`, { signal }),
    enabled: Boolean(chartTicker && chartDate) && tab === "chart",
  });
  const start = useMutation({
    mutationFn: (body: ResearchFormState) =>
      api<AnalysisRecord>("/api/analyses", {
        method: "POST",
        body: JSON.stringify({ ...body, ticker: body.ticker.trim(), backend_url: body.backend_url.trim() || null }),
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

  const record = analysis.data;
  const completed = record?.status === "completed";
  const showSetupInline = !record;
  const latest = record?.activity?.[record.activity.length - 1];
  const levels = levelsFrom(record?.trade_plan);
  const busy = start.isPending || (active.data ?? []).some((row) => ACTIVE.has(row.status));

  function closeSetup() {
    setSetupOpen(false);
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="num text-3xl leading-none">{record?.ticker ?? form?.ticker ?? t("nav.research")}</h1>
            <span className="text-xs text-muted">{record?.analysis_date ?? form?.analysis_date ?? t("research.date")}</span>
            <span className="text-xs text-muted">{record ? textLabel(t, "run", record.status) : t("research.notStarted")}</span>
          </div>
          {record?.finished_at || record?.created_at ? (
            <p className="mt-1 text-[11px] text-faint">{t("research.generated")} {formatWhen(record.finished_at ?? record.created_at)}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {record && ACTIVE.has(record.status) && (
            <Button type="button" variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              {t("common.cancel")}
            </Button>
          )}
          {record && (
            <Button ref={setupButton} type="button" variant="outline" onClick={() => setSetupOpen(true)}>{t("research.setup")}</Button>
          )}
          <Button type="button" variant="outline" onClick={() => navigate("/research")}>{t("research.new")}</Button>
        </div>
      </header>
      {record && (
        <div className="grid border border-line bg-paper text-xs sm:grid-cols-3" aria-label="Research status">
          <div className="border-b border-line px-3 py-1.5 sm:border-r sm:border-b-0">
            <div className="text-[10px] tracking-wide text-faint uppercase">{t("research.flow")}</div>
            <div>{textLabel(t, "run", record.status)}</div>
          </div>
          <div className="border-b border-line px-3 py-1.5 sm:border-r sm:border-b-0">
            <div className="text-[10px] tracking-wide text-faint uppercase">{t("research.rating")}</div>
            <RatingMark rating={record.decision?.result_status === "readable" ? (record.decision.rating ?? record.rating) : null} unknown={t("research.needsReview")} />
          </div>
          <div className="px-3 py-1.5">
            <div className="text-[10px] tracking-wide text-faint uppercase">{t("research.planState")}</div>
            <div>{t(`planState.${record.decision?.plan_status ?? "none"}`)}</div>
          </div>
        </div>
      )}
      {mode === "copy" && !analysisId && <p className="copy text-sm text-muted">{t("research.copied")}</p>}
      {record && !ACTIVE.has(record.status) && record.status !== "completed" && (
        <Panel title={t("research.stopped")}>
          <p className="text-sm text-danger">{record.error_code}: {record.error}</p>
          <p className="mt-2 text-sm text-muted">{t("research.kept")}</p>
        </Panel>
      )}
      {options.isError && <p role="alert" className="text-sm text-danger">{t("research.configError")} {options.error.message}</p>}
      {analysis.isError && (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-danger">{t("research.loadError")} {analysis.error.message}</p>
          <Button type="button" variant="outline" onClick={() => analysis.refetch()}>{t("common.retry")}</Button>
        </div>
      )}
      {showSetupInline && (
        <Panel title={t("research.setup")}>
          {!form || !options.data ? <p className="text-sm text-muted">{t("research.loadingConfig")}</p> : (
            <ResearchSetup
              form={form}
              setForm={setForm}
              options={options.data}
              advanced={advanced}
              setAdvanced={setAdvanced}
              busy={busy}
              onSubmit={() => start.mutate(form)}
              onWatch={() => addWatch.mutate(form.ticker.trim())}
              watchPending={addWatch.isPending}
              showRestore={mode === "copy"}
            />
          )}
          {start.isError && <p className="mt-2 text-xs text-danger">{start.error.message}</p>}
          {watchMessage && <p className="mt-2 text-xs text-muted">{watchMessage}</p>}
        </Panel>
      )}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Research sections">
          <TabsTrigger value="summary">{t("research.summary")}</TabsTrigger>
          <TabsTrigger value="chart">{t("research.chart")}</TabsTrigger>
          <TabsTrigger value="plan">{t("research.plan")}</TabsTrigger>
          <TabsTrigger value="report">{t("research.report")}</TabsTrigger>
          <TabsTrigger value="log">{t("research.log")}</TabsTrigger>
        </TabsList>
        <TabsContent value="summary">
          <Panel title={t("research.summary")}>
            {running && (
              <p className="copy text-sm text-muted">
                {t("research.phase")}: {textLabel(t, "phase", record?.phase ?? "queued")}. {t("research.latest")}: {latest?.message ?? t("research.waiting")} {t("research.noPercent")}
              </p>
            )}
            {!record && <p className="copy text-sm text-muted">{t("research.noConclusion")}</p>}
            {record?.trade_plan && record.decision && <Conclusion record={record} />}
            {record && !record.trade_plan && !running && <p className="text-sm text-muted">{t("research.noPlan")}</p>}
            {completed && record && (
              <p className="mt-3 text-xs text-muted">
                {t("research.outputLanguage")}: {record.settings.output_language ?? t("common.unknown")}. {t("research.interfaceLanguage")}: {locale === "zh" ? "中文" : "English"}.
              </p>
            )}
          </Panel>
        </TabsContent>
        <TabsContent value="chart">
          <Panel title={chartTicker ? `${chartTicker}` : t("research.chart")}>
            {market.isLoading && <p className="text-sm text-muted">{t("chart.loading")}</p>}
            {market.error && <p className="text-sm text-danger">{t("chart.failed")} {market.error.message}</p>}
            {market.data && (
              <>
                <ResearchSnapshot snapshot={record?.data_sources} fresh={market.data} />
                <div className="mb-3 flex flex-wrap items-end justify-between gap-3 text-sm">
                  <div>
                    <div className="num text-2xl">{formatNumber(market.data.reference_price)}</div>
                    <p className="text-xs text-muted">{market.data.bar_date || t("common.unknown")} · {market.data.currency || t("common.unknown")} · {market.data.source || t("common.unknown")}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted">
                    {RANGES.map((item) => (
                      <button key={item.id} type="button" className={rangeBars === item.bars ? "text-ink" : ""} onClick={() => setRangeBars(item.bars)}>{item.id}</button>
                    ))}
                    <label className="flex items-center gap-1"><input type="checkbox" checked={showRsi} onChange={() => setShowRsi((value) => !value)} /> RSI</label>
                    <label className="flex items-center gap-1"><input type="checkbox" checked={showMacd} onChange={() => setShowMacd((value) => !value)} /> MACD</label>
                  </div>
                </div>
                <PriceChart candles={market.data.candles} levels={levels} showRsi={showRsi} showMacd={showMacd} rangeBars={rangeBars} />
              </>
            )}
          </Panel>
        </TabsContent>
        <TabsContent value="plan">
          <Panel title={t("research.plan")}>
            <TradePlanPanel analysisId={analysisId} ticker={record?.ticker} plan={record?.trade_plan} decision={record?.decision} />
          </Panel>
        </TabsContent>
        <TabsContent value="report">
          <Panel title={t("research.report")} action={<Button type="button" variant="ghost" onClick={() => setTab("summary")}>{t("research.backSummary")}</Button>}>
            <ReportTabs reports={record?.reports} />
            {record?.html_report_path && (
              <a className="mt-3 inline-block text-sm text-accent" href={`/api/analyses/${record.id}/report`}>{t("report.export")}</a>
            )}
          </Panel>
        </TabsContent>
        <TabsContent value="log">
          <Panel title={t("research.log")}>
            <AgentWorkflow phase={record?.phase ?? "queued"} agentStatus={record?.agent_status ?? {}} activity={record?.activity ?? []} />
            {record?.error && <p className="mt-3 text-sm text-danger">{t("log.error")}: {record.error_code}: {record.error}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              {record && ACTIVE.has(record.status) && <Button type="button" variant="outline" onClick={() => cancel.mutate()}>{t("common.cancel")}</Button>}
              <Button type="button" variant="outline" onClick={() => setTab("summary")}>{t("research.openSummary")}</Button>
              <Button type="button" variant="outline" onClick={() => setTab("report")}>{t("research.openReport")}</Button>
              <Button type="button" variant="ghost" onClick={() => navigate("/research")}>{t("research.newForm")}</Button>
            </div>
            <ToolNotes sources={record?.data_sources} />
          </Panel>
        </TabsContent>
      </Tabs>
      <Dialog open={setupOpen} title={t("research.setup")} onClose={closeSetup} returnFocus={setupButton}>
        {record && <SavedRunSummary record={record} />}
        {form && options.data ? (
          <ResearchSetup
            form={form}
            setForm={setForm}
            options={options.data}
            advanced={advanced}
            setAdvanced={setAdvanced}
            busy={busy}
            onSubmit={() => start.mutate(form)}
            onWatch={() => addWatch.mutate(form.ticker.trim())}
            watchPending={addWatch.isPending}
            showCopy={completed}
            onCopy={record ? () => { setSetupOpen(false); navigate(`/research?from=${record.id}`); } : undefined}
          />
        ) : <p className="text-sm text-muted">{t("research.loadingConfig")}</p>}
        <div className="mt-3">
          <Button type="button" variant="ghost" onClick={() => setSetupOpen(false)}>{t("common.close")}</Button>
        </div>
      </Dialog>
      <Dialog
        open={blocker.state === "blocked"}
        title={t("research.leaveTitle")}
        onClose={() => {
          if (leaving.current) {
            leaving.current = false;
            return;
          }
          if (blocker.state === "blocked") blocker.reset();
        }}
      >
        <p className="copy text-sm text-muted">{t("research.leaveBody")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" onClick={() => { leaving.current = true; if (blocker.state === "blocked") blocker.proceed(); }}>{t("research.keep")}</Button>
          <Button type="button" variant="outline" onClick={() => { leaving.current = true; discardSession(key); if (blocker.state === "blocked") blocker.proceed(); }}>{t("research.discard")}</Button>
          <Button type="button" variant="ghost" onClick={() => blocker.state === "blocked" && blocker.reset()}>{t("research.stay")}</Button>
        </div>
      </Dialog>
    </div>
  );
}

function Conclusion({ record }: { record: AnalysisRecord }) {
  const { t } = useLocale();
  const decision = record.decision;
  const market = record.trade_plan?.verified_market;
  return (
    <div className="space-y-3">
      <RatingMark rating={decision?.rating} unknown={t("research.needsReview")} />
      <div>
        <h3 className="text-xs text-muted">{t("research.conditions")}</h3>
        <p className="copy mt-1 whitespace-pre-wrap text-sm">{decision?.conditions || t("common.unknown")}</p>
      </div>
      {decision?.thesis && (
        <details className="rounded-md border border-line px-3 py-2">
          <summary className="cursor-pointer text-sm">{t("research.thesis")}</summary>
          <p className="copy mt-2 whitespace-pre-wrap text-sm">{decision.thesis}</p>
        </details>
      )}
      <p className="text-xs text-muted">
        {t("research.reference")}: {market?.price == null ? t("common.unknown") : formatNumber(market.price)}
        {" · "}{market?.bar_date || t("common.unknown")}
        {" · "}{market?.currency || t("common.unknown")}
        {!market?.currency && ` · ${t("plan.currencyMissing")}`}
        {" · "}{market?.source || t("common.unknown")}
      </p>
      <details className="text-xs text-muted">
        <summary>{t("research.diagnostics")}</summary>
        <div className="mt-2 space-y-1">
          {decision?.action_note && <p>{decision.action_note}</p>}
          <p>{t("research.noPercent")}</p>
          <ToolNotes sources={record.data_sources} />
        </div>
      </details>
    </div>
  );
}

function ResearchSnapshot({
  snapshot,
  fresh,
}: {
  snapshot: AnalysisRecord["data_sources"] | undefined;
  fresh: MarketChart;
}) {
  const { t } = useLocale();
  const sources = snapshot as { research_market?: { price?: number | null; bar_date?: string | null; source?: string | null; currency?: string | null; role?: string }; market?: { price?: number | null; bar_date?: string | null; source?: string | null; currency?: string | null } } | undefined;
  const saved = sources?.research_market ?? sources?.market;
  const label = sources?.research_market ? t("plan.snapshot") : t("plan.stored");
  return (
    <div className="mb-3 space-y-1 text-xs text-muted">
      <p>{label}: {saved?.bar_date || t("common.unknown")} · {saved?.price ?? t("common.unknown")} · {saved?.currency || t("common.unknown")} · {saved?.source || t("common.unknown")}</p>
      <p>{t("plan.calculation")}: {fresh.bar_date || t("common.unknown")} · {fresh.reference_price ?? t("common.unknown")} · {fresh.currency || t("common.unknown")} · {fresh.source || t("common.unknown")}</p>
    </div>
  );
}

function SavedRunSummary({ record }: { record: AnalysisRecord }) {
  const { t, locale } = useLocale();
  const settings = record.settings;
  const depth = t(`depth.${settings.research_depth ?? 1}`);
  return (
    <div className="mb-3 space-y-1 text-xs leading-5 text-muted">
      <p>{record.ticker} · {record.analysis_date} · {(settings.analysts ?? []).join(", ") || t("common.unknown")} · {depth}</p>
      <p>{t("research.outputLanguage")}: {settings.output_language ?? t("common.unknown")}. {t("research.interfaceLanguage")}: {locale === "zh" ? "中文" : "English"}.</p>
      <p>{t("history.model")}: {settings.quick_think_llm || t("common.unknown")} / {settings.deep_think_llm || t("common.unknown")}.</p>
    </div>
  );
}

function ToolNotes({ sources }: { sources: AnalysisRecord["data_sources"] | undefined }) {
  const { t } = useLocale();
  if (!sources) return null;
  const record = sources as {
    memory_error?: string | null;
    report_error?: string | null;
    estimated_cost?: { status?: string; reason?: string };
    usage?: { input_tokens?: number; output_tokens?: number; calls_with_usage?: number; cache_tokens?: number; cached_tokens?: number };
  };
  const usage = record.usage;
  const cache = usage?.cache_tokens ?? usage?.cached_tokens;
  const costKnown = record.estimated_cost?.status === "known";
  return (
    <div className="mt-3 space-y-1 text-xs text-muted">
      <p>{t("usage.cost")}: {costKnown ? record.estimated_cost?.status : t("usage.costUnknown")}. {record.estimated_cost?.reason ?? ""}</p>
      <p>
        {t("usage.tokens")}: {t("usage.input")} {usage?.input_tokens ?? t("usage.notRecorded")}, {t("usage.output")} {usage?.output_tokens ?? t("usage.notRecorded")}.
        {" "}{t("usage.calls")}: {usage?.calls_with_usage ?? t("usage.notRecorded")}. {t("usage.callsNote")}
      </p>
      <p>{t("usage.cache")}: {cache ?? t("usage.notRecorded")}.</p>
      {[record.memory_error, record.report_error].filter(Boolean).map((note) => <p key={note}>{note}</p>)}
    </div>
  );
}

function textLabel(t: (key: string) => string, prefix: string, id: string) {
  const key = `${prefix}.${id}`;
  const value = t(key);
  return value === key ? id.replaceAll("_", " ") : value;
}

function levelsFrom(plan: AnalysisRecord["trade_plan"]): ChartLevel[] {
  const hypotheses = plan?.hypotheses;
  if (!hypotheses) return [];
  const levels: ChartLevel[] = [];
  if (hypotheses.entry_price !== null) levels.push({ price: hypotheses.entry_price, title: "Hypothesis entry", color: "#8a5a00" });
  if (hypotheses.stop_loss !== null) levels.push({ price: hypotheses.stop_loss, title: "Hypothesis stop", color: "#c4233c" });
  if (hypotheses.price_target !== null) levels.push({ price: hypotheses.price_target, title: "Hypothesis target", color: "#0c7a43" });
  return levels;
}
