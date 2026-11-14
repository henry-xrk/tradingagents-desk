import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { StatusText } from "../components/StatusText.tsx";
import { Button } from "../components/ui/button.tsx";
import { Input, Select } from "../components/ui/input.tsx";
import { useLocale } from "../i18n.tsx";
import { popHistoryCursor, pushHistoryCursor } from "../lib/historyQuery.ts";
import { formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { AnalysisRecord, HistoryPage as HistoryResponse } from "../types/api.ts";

const ACTIVE = new Set(["queued", "running", "cancel_requested", "cancelling"]);
const STATUSES = ["queued", "running", "completed", "failed", "timed_out", "stopped", "interrupted"];

export function HistoryPage() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const urlTicker = params.get("ticker") ?? "";
  const status = params.get("status") ?? "";
  const date = params.get("date") ?? "";
  const cursor = params.get("cursor") ?? "";
  const stack = params.get("stack") ?? "";
  const [tickerDraft, setTickerDraft] = useState(urlTicker);
  const [seenTicker, setSeenTicker] = useState(urlTicker);
  if (urlTicker !== seenTicker) {
    setSeenTicker(urlTicker);
    setTickerDraft(urlTicker);
  }

  useEffect(() => {
    const handle = window.setTimeout(() => {
      const normalized = tickerDraft.trim().toUpperCase();
      if (normalized === urlTicker) return;
      const next = new URLSearchParams(params);
      if (normalized) next.set("ticker", normalized);
      else next.delete("ticker");
      next.delete("cursor");
      next.delete("stack");
      setParams(next, { replace: true });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [tickerDraft, urlTicker, params, setParams]);

  const query = new URLSearchParams({ limit: "50" });
  if (urlTicker) query.set("ticker", urlTicker);
  if (status) query.set("status", status);
  if (date) query.set("analysis_date", date);
  if (cursor) query.set("cursor", cursor);
  const history = useQuery({
    queryKey: ["analyses", urlTicker, status, date, cursor],
    queryFn: ({ signal }) => api<HistoryResponse>(`/api/history?${query.toString()}`, { signal }),
    refetchInterval: (query) => ((query.state.data?.items ?? []).some((row) => ACTIVE.has(row.status)) ? 5000 : false),
  });

  function setFilter(key: "status" | "date", value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("cursor");
    next.delete("stack");
    setParams(next, { replace: true });
  }

  function older() {
    const nextCursor = history.data?.next_cursor;
    if (!nextCursor) return;
    const moved = pushHistoryCursor(stack, cursor, nextCursor);
    const next = new URLSearchParams(params);
    next.set("cursor", moved.cursor);
    next.set("stack", moved.stack);
    setParams(next);
  }

  function newer() {
    const moved = popHistoryCursor(stack);
    const next = new URLSearchParams(params);
    if (!moved || !moved.cursor) next.delete("cursor");
    else next.set("cursor", moved.cursor);
    if (!moved || !moved.stack) next.delete("stack");
    else next.set("stack", moved.stack);
    setParams(next);
  }

  const items = history.data?.items ?? [];
  const filtered = Boolean(urlTicker || status || date);
  const depth = (value: number | undefined) => t(`depth.${value ?? 1}`);

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4">
      <div>
        <h1 className="text-xl font-medium">{t("history.title")}</h1>
        <p className="copy mt-1 text-sm text-muted">{t("history.lead")}</p>
      </div>
      <form className="grid gap-2 md:grid-cols-3" onSubmit={(event) => event.preventDefault()}>
        <Input aria-label={t("history.ticker")} placeholder={t("history.ticker")} value={tickerDraft} onChange={(event) => setTickerDraft(event.target.value.toUpperCase())} className="font-mono uppercase" />
        <Input aria-label={t("history.date")} type="date" value={date} onChange={(event) => setFilter("date", event.target.value)} />
        <Select aria-label={t("history.status")} value={status} onChange={(event) => setFilter("status", event.target.value)}>
          <option value="">{t("history.any")}</option>
          {STATUSES.map((item) => <option key={item} value={item}>{label(t, "run", item)}</option>)}
        </Select>
      </form>
      {history.isPending && <p className="text-sm text-muted">{t("history.loading")}</p>}
      {history.isError && (
        <div role="alert" className="space-y-2">
          <p className="text-sm text-danger">{t("history.error")} {history.error.message}</p>
          <Button type="button" variant="outline" onClick={() => history.refetch()}>{t("common.retry")}</Button>
        </div>
      )}
      {history.isSuccess && items.length === 0 && (
        <p className="text-sm text-muted">{filtered || cursor ? t("history.noMatch") : t("history.none")}</p>
      )}
      {items.length > 0 && (
        <>
          <div className="border-t border-line lg:hidden">
            {items.map((row) => <HistoryCard key={row.id} row={row} depth={depth(row.settings.research_depth)} />)}
          </div>
          <div className="hidden overflow-x-auto border border-line bg-paper lg:block">
            <table className="w-full min-w-[860px] text-left text-sm">
              <thead className="text-[11px] tracking-wide text-faint uppercase">
                <tr>
                  <th className="px-2 py-1 font-medium">{t("shell.ticker")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.saved")}</th>
                  <th className="px-2 py-1 font-medium">{t("research.date")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.status")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.depth")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.model")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.rating")}</th>
                  <th className="px-2 py-1 font-medium">{t("history.plan")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-t border-line">
                    <td className="px-2 py-1">
                      <Link className="num" to={`/research/${row.id}`}>{row.ticker}</Link>
                      <div><Link className="text-[11px] text-accent" to={`/research?from=${row.id}`}>{t("history.copy")}</Link></div>
                    </td>
                    <td className="num px-2 py-1 text-xs text-muted">{formatWhen(row.created_at)}</td>
                    <td className="num px-2 py-1">{row.analysis_date}</td>
                    <td className="px-2 py-1"><RunStatus status={row.status} /></td>
                    <td className="px-2 py-1">{depth(row.settings.research_depth)}</td>
                    <td className="px-2 py-1 text-xs text-muted">{row.settings.quick_think_llm || t("common.unknown")} / {row.settings.deep_think_llm || t("common.unknown")}</td>
                    <td className="px-2 py-1">{row.rating === "REVIEW" ? t("history.noRating") : row.rating ?? "—"}</td>
                    <td className="num px-2 py-1">{row.plan_version ? `v${row.plan_version}` : row.has_trade_plan ? t("plan.saved") : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={!stack} onClick={newer}>{t("history.newer")}</Button>
            <Button type="button" variant="outline" disabled={!history.data?.next_cursor} onClick={older}>{t("history.older")}</Button>
          </div>
        </>
      )}
    </div>
  );
}

function HistoryCard({ row, depth }: { row: AnalysisRecord; depth: string }) {
  const { t } = useLocale();
  return (
    <article className="border-b border-line py-1.5 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <Link className="num" to={`/research/${row.id}`}>{row.ticker}</Link>
        <RunStatus status={row.status} />
      </div>
      <p className="text-xs text-muted">{row.analysis_date} · {depth}</p>
      <p className="text-xs text-muted">{row.settings.quick_think_llm || t("common.unknown")} / {row.settings.deep_think_llm || t("common.unknown")} · {formatWhen(row.created_at)}</p>
      <Link className="text-xs text-accent" to={`/research?from=${row.id}`}>{t("history.copy")}</Link>
    </article>
  );
}

function RunStatus({ status }: { status: string }) {
  const { t } = useLocale();
  const tone = status === "completed" ? "ok" : status === "failed" || status === "timed_out" ? "danger" : ACTIVE.has(status) ? "warn" : "neutral";
  return <StatusText tone={tone}>{label(t, "run", status)}</StatusText>;
}

function label(t: (key: string) => string, prefix: string, id: string): string {
  const key = `${prefix}.${id}`;
  const value = t(key);
  return value === key ? id.replaceAll("_", " ") : value;
}
