import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Input, Select } from "../components/ui/input.tsx";
import { formatWhen } from "../lib/utils.ts";
import { api } from "../services/api.ts";
import type { AnalysisRecord } from "../types/api.ts";

const ACTIVE = new Set(["queued", "running", "cancel_requested", "cancelling"]);

export function HistoryPage() {
  const [ticker, setTicker] = useState("");
  const [status, setStatus] = useState("");
  const [date, setDate] = useState("");
  const params = new URLSearchParams({ limit: "100" });
  if (ticker.trim()) params.set("ticker", ticker.trim());
  if (status) params.set("status", status);
  if (date) params.set("analysis_date", date);
  const history = useQuery({
    queryKey: ["analyses", ticker, status, date],
    queryFn: () => api<AnalysisRecord[]>(`/api/history?${params.toString()}`),
    refetchInterval: (query) => ((query.state.data ?? []).some((row) => ACTIVE.has(row.status)) ? 5000 : false),
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-medium">History</h1>
        <p className="mt-1 text-sm text-[#4d5d6d]">
          Saved runs keep their settings, reports, and plan version. Opening one does not replace it.
        </p>
      </div>
      <form className="grid gap-2 sm:grid-cols-3" onSubmit={(event) => event.preventDefault()}>
        <Input aria-label="Filter ticker" placeholder="Ticker" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} className="font-mono uppercase" />
        <Input aria-label="Filter date" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        <Select aria-label="Filter status" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">Any status</option>
          {["queued", "running", "completed", "failed", "timed_out", "stopped", "interrupted"].map((item) => (
            <option key={item} value={item}>{item.replaceAll("_", " ")}</option>
          ))}
        </Select>
      </form>
      {history.isLoading && <p className="text-sm text-[#4d5d6d]">Loading history.</p>}
      {history.error && <p className="text-sm text-[#b42334]">{history.error.message}</p>}
      <div className="overflow-x-auto rounded-lg border border-[#d5dee6]">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="bg-[#ffffff] text-[11px] tracking-wide text-[#6b7c8d] uppercase">
            <tr>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Date</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Rating</th>
              <th className="px-3 py-2 font-medium">Reports</th>
              <th className="px-3 py-2 font-medium">Plan</th>
              <th className="px-3 py-2 font-medium">Saved</th>
            </tr>
          </thead>
          <tbody>
            {(history.data ?? []).map((row) => (
              <tr key={row.id} className="border-t border-[#d5dee6]">
                <td className="px-3 py-2 font-mono">
                  <Link to={`/research/${row.id}`}>{row.ticker}</Link>
                </td>
                <td className="px-3 py-2">{row.analysis_date}</td>
                <td className="px-3 py-2">{row.status.replaceAll("_", " ")}</td>
                <td className="px-3 py-2">{row.rating === "REVIEW" ? "No readable rating" : row.rating ?? "—"}</td>
                <td className="px-3 py-2">
                  {row.has_partial_report && <span className="mr-2">Partial</span>}
                  {row.html_report_path ? (
                    <a className="text-[#1a56a8]" href={`/api/analyses/${row.id}/report`}>HTML</a>
                  ) : (
                    <span className="text-[#6b7c8d]">No HTML</span>
                  )}
                </td>
                <td className="px-3 py-2">{row.plan_version ? `v${row.plan_version}` : row.has_trade_plan ? "Saved" : "None"}</td>
                <td className="px-3 py-2">
                  <div className="text-[#4d5d6d]">{formatWhen(row.created_at)}</div>
                  <Link className="text-xs text-[#1a56a8]" to={`/research?from=${row.id}`}>New from these settings</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(history.data ?? []).length === 0 && !history.isLoading && (
          <p className="px-3 py-4 text-sm text-[#4d5d6d]">No saved analyses match these filters.</p>
        )}
      </div>
    </div>
  );
}
