import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Panel } from "../components/AgentWorkflow.tsx";
import { Button } from "../components/ui/button.tsx";
import { Input } from "../components/ui/input.tsx";
import { useLocale } from "../i18n.tsx";
import { formatNumber, formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { AnalysisRecord, HistoryPage, WatchlistResponse } from "../types/api.ts";

const ACTIVE = new Set(["queued", "running", "cancel_requested", "cancelling"]);
const ATTENTION = new Set(["failed", "timed_out", "interrupted", "stopped"]);

export function OverviewPage() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const active = useQuery({
    queryKey: ["analyses", "active"],
    queryFn: ({ signal }) => api<AnalysisRecord[]>("/api/analyses/active", { signal }),
    refetchInterval: 5000,
  });
  const history = useQuery({
    queryKey: ["analyses", "overview"],
    queryFn: ({ signal }) => api<HistoryPage>("/api/history?limit=12", { signal }),
  });
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: ({ signal }) => api<WatchlistResponse>("/api/watchlist", { signal }),
  });
  const add = useMutation({
    mutationFn: (symbol: string) => api<{ ticker: string }>("/api/watchlist", { method: "POST", body: JSON.stringify({ ticker: symbol }) }),
    onSuccess: async () => {
      setTicker("");
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
  const remove = useMutation({
    mutationFn: (symbol: string) => api<{ ticker: string }>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
  const rows = history.data?.items ?? [];
  const attention = rows.filter((row) => ATTENTION.has(row.status));

  function onAdd(event: FormEvent) {
    event.preventDefault();
    if (!ticker.trim()) return;
    add.mutate(ticker.trim());
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium">{t("overview.title")}</h1>
          <p className="copy mt-1 text-sm text-muted">{t("overview.lead")}</p>
        </div>
        <Button type="button" onClick={() => navigate("/research")}>{t("overview.new")}</Button>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title={t("overview.active")}>
          <QueryState loading={active.isPending} error={active.error} onRetry={() => active.refetch()} empty={!active.isPending && !active.isError && (active.data ?? []).length === 0} emptyText={t("overview.activeEmpty")} />
          <ul>
            {(active.data ?? []).map((row) => (
              <li key={row.id} className="border-b border-line py-1 last:border-0">
                <Link to={`/research/${row.id}`} className="flex items-center justify-between gap-3 text-sm">
                  <span className="num">{row.ticker}</span>
                  <span className="text-xs text-warn">{textLabel(t, "phase", row.phase)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title={t("overview.recent")}>
          <QueryState loading={history.isPending} error={history.error} onRetry={() => history.refetch()} empty={history.isSuccess && rows.length === 0} emptyText={t("overview.recentEmpty")} errorText={t("overview.historyError")} />
          <HistoryList rows={rows.filter((row) => !ACTIVE.has(row.status)).slice(0, 6)} />
        </Panel>
        <Panel title={t("overview.attention")}>
          <QueryState loading={history.isPending} error={null} onRetry={() => history.refetch()} empty={history.isSuccess && attention.length === 0} emptyText={t("overview.attentionEmpty")} />
          <HistoryList rows={attention.slice(0, 6)} />
        </Panel>
      </div>
      <Panel title={t("overview.watchlist")}>
        <form onSubmit={onAdd} className="mb-3 flex max-w-md gap-2">
          <Input aria-label={t("overview.add")} value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder={t("overview.add")} className="font-mono uppercase" />
          <Button type="submit" variant="outline" disabled={add.isPending || !ticker.trim()}>{t("overview.addButton")}</Button>
        </form>
        {add.isError && <p className="mb-2 text-xs text-danger">{add.error.message}</p>}
        <QueryState loading={watchlist.isPending} error={watchlist.error} onRetry={() => watchlist.refetch()} empty={watchlist.isSuccess && (watchlist.data?.items.length ?? 0) === 0} emptyText={t("overview.emptyWatch")} />
        {(watchlist.data?.items.length ?? 0) > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="text-[11px] tracking-wide text-faint uppercase">
                <tr>
                  <th className="py-1 pr-3 font-medium">{t("shell.ticker")}</th>
                  <th className="py-1 pr-3 font-medium">{t("overview.close")}</th>
                  <th className="py-1 pr-3 font-medium">{t("quote.asOf")}</th>
                  <th className="py-1 font-medium">{t("overview.quality")}</th>
                </tr>
              </thead>
              <tbody>
                {watchlist.data?.items.map((item) => (
                  <tr key={item.ticker} className="border-t border-line">
                    <td className="num py-1 pr-3"><Link to={`/research?ticker=${encodeURIComponent(item.ticker)}`}>{item.ticker}</Link></td>
                    <td className="num py-1 pr-3">{item.ok ? formatNumber(item.price ?? null) : <span className="text-danger">{item.error ?? t("quote.noPrice")}</span>}</td>
                    <td className="num py-1 pr-3 text-muted">{item.bar_date ?? t("common.unknown")}</td>
                    <td className="py-1 text-right">
                      <span className="mr-2 text-xs text-muted">{item.ok ? t("overview.loaded") : t("quote.noPrice")}</span>
                      <Button variant="ghost" size="sm" onClick={() => remove.mutate(item.ticker)}>{t("overview.remove")}</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-faint">{t("quote.notLive")}</p>
      </Panel>
    </div>
  );
}

function QueryState({
  loading,
  error,
  onRetry,
  empty,
  emptyText,
  errorText,
}: {
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  empty: boolean;
  emptyText: string;
  errorText?: string;
}) {
  const { t } = useLocale();
  if (loading) return <p className="text-sm text-muted">{t("common.loading")}</p>;
  if (error) {
    return (
      <div role="alert" className="space-y-2">
        <p className="text-sm text-danger">{errorText ?? error.message}</p>
        <Button type="button" variant="outline" onClick={onRetry}>{t("common.retry")}</Button>
      </div>
    );
  }
  if (empty) return <p className="text-sm text-muted">{emptyText}</p>;
  return null;
}

function HistoryList({ rows }: { rows: AnalysisRecord[] }) {
  const { t } = useLocale();
  if (rows.length === 0) return null;
  return (
    <ul>
      {rows.map((row) => (
        <li key={row.id} className="border-b border-line py-1 text-sm last:border-0">
          <Link to={`/research/${row.id}`} className="num">{row.ticker}</Link>
          <div className="text-xs text-muted">{row.analysis_date} · {textLabel(t, "run", row.status)} · {row.rating === "REVIEW" ? t("history.noRating") : row.rating ?? t("history.noRating")}</div>
          <div className="text-[11px] text-faint">{formatWhen(row.created_at)} · {row.settings.quick_think_llm || t("common.unknown")}</div>
        </li>
      ))}
    </ul>
  );
}

function textLabel(t: (key: string) => string, prefix: string, id: string) {
  const key = `${prefix}.${id}`;
  const value = t(key);
  return value === key ? id.replaceAll("_", " ") : value;
}
