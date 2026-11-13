import { useQuery } from "@tanstack/react-query";
import { History, LayoutDashboard, LineChart, Settings } from "lucide-react";
import type { FormEvent, ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { api } from "../../services/api.ts";
import type { ConfigOptions, WatchlistResponse } from "../../types/api.ts";
import { cn, formatNumber } from "../../lib/utils.ts";

const links = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/research", label: "Research", icon: LineChart, end: false },
  { to: "/history", label: "History", icon: History, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

export function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const auth = useQuery({
    queryKey: ["options"],
    queryFn: () => api<ConfigOptions>("/api/config/options"),
    staleTime: 30_000,
  });
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => api<WatchlistResponse>("/api/watchlist"),
    refetchInterval: 60_000,
  });

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ticker = String(data.get("ticker") ?? "").trim();
    if (!ticker) return;
    navigate(`/research?ticker=${encodeURIComponent(ticker)}`);
  }

  return (
    <div className="flex min-h-full flex-col bg-[#f3f5f7] text-[#1a2330] lg:flex-row">
      <aside className="border-b border-[#d5dee6] lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-56 lg:flex-col lg:border-r lg:border-b-0">
        <div className="px-4 py-4">
          <div className="font-mono text-[10px] tracking-[0.22em] text-[#6b7c8d]">TRADINGAGENTS</div>
          <div className="mt-1 text-base font-medium">Research Desk</div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 lg:flex-col lg:px-2">
          {links.map((link) => {
            const Icon = link.icon;
            return (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm text-[#4d5d6d]",
                  isActive && "bg-[#e8eef3] text-[#1a2330]",
                )
              }
            >
              <Icon className="size-4" />
              {link.label}
            </NavLink>
            );
          })}
        </nav>
        <div className="mt-auto hidden px-4 py-4 text-xs text-[#4d5d6d] lg:block">
          <div className="font-mono text-[10px] tracking-wide text-[#6b7c8d]">OPENAI API</div>
          <div className="mt-1 truncate">{auth.isError ? "Connection unavailable" : !auth.data ? "Checking configuration…" : auth.data.providers.find((provider) => provider.id === "openai")?.auth_message ? "API key not configured" : "API key configured · not verified"}</div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-col gap-3 border-b border-[#d5dee6] px-4 py-3 lg:flex-row lg:items-center">
          <form onSubmit={search} className="flex w-full max-w-sm gap-2">
            <input
              name="ticker"
              aria-label="Ticker"
              placeholder="Ticker"
              className="h-9 w-full rounded-md border border-[#b7c4d0] bg-white px-3 font-mono text-sm uppercase text-[#1a2330] outline-none focus:border-[#1a56a8]"
            />
            <button type="submit" className="h-9 rounded-md border border-[#b7c4d0] px-3 text-sm text-[#3d4d5c]">
              Open
            </button>
          </form>
          <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto">
            {watchlist.data?.items.map((item) => (
              <button
                key={item.ticker}
                type="button"
                onClick={() => navigate(`/research?ticker=${encodeURIComponent(item.ticker)}`)}
                className="shrink-0 rounded-md border border-[#d5dee6] bg-[#ffffff] px-2.5 py-1.5 text-left"
              >
                <div className="font-mono text-xs">{item.ticker}</div>
                <div className={cn("font-mono text-[11px]", changeClass(item.change))}>
                  {item.ok ? formatNumber(item.price ?? null) : "No price"}
                </div>
              </button>
            ))}
            {watchlist.isLoading && <span className="self-center text-xs text-[#6b7c8d]">Loading watchlist</span>}
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-4">{children}</main>
      </div>
    </div>
  );
}

function changeClass(change: number | null | undefined) {
  if (change === null || change === undefined) return "text-[#4d5d6d]";
  return change >= 0 ? "text-[#0c7a43]" : "text-[#c4233c]";
}
