import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, LayoutDashboard, LineChart, Settings } from "lucide-react";
import type { FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useLocale } from "../../i18n.tsx";
import { cn, formatNumber, formatWhen } from "../../lib/utils.ts";
import { api } from "../../services/api.ts";
import type { SystemStatus, WatchlistResponse } from "../../types/api.ts";
import { providerCheckedAt, providerStatusCode } from "../ProviderStatus.tsx";

export function AppShell() {
  const { t, locale, setLocale } = useLocale();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const auth = useQuery({
    queryKey: ["system"],
    queryFn: ({ signal }) => api<SystemStatus>("/api/system", { signal }),
    staleTime: 30_000,
  });
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: ({ signal }) => api<WatchlistResponse>("/api/watchlist", { signal }),
    refetchInterval: 60_000,
  });
  const links = [
    { to: "/", label: t("nav.overview"), icon: LayoutDashboard, end: true },
    { to: "/research", label: t("nav.research"), icon: LineChart, end: false },
    { to: "/history", label: t("nav.history"), icon: History, end: false },
    { to: "/settings", label: t("nav.settings"), icon: Settings, end: false },
  ];
  const removeWatch = useMutation({
    mutationFn: (symbol: string) => api<{ ticker: string }>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
  });
  const code = providerStatusCode(auth.data, auth.isLoading, auth.isError);
  const checked = providerCheckedAt(auth.data);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const ticker = String(data.get("ticker") ?? "").trim();
    if (!ticker) return;
    navigate(`/research?ticker=${encodeURIComponent(ticker)}`);
    event.currentTarget.reset();
  }

  return (
    <div className="flex min-h-full flex-col bg-canvas text-ink lg:flex-row">
      <aside className="border-b border-line bg-paper lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-44 lg:shrink-0 lg:flex-col lg:border-r lg:border-b-0">
        <div className="whitespace-nowrap px-3 py-3 font-mono text-xs font-medium tracking-wide text-ink">Research Desk</div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 lg:flex-col lg:px-0" aria-label="Primary">
          {links.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) => cn("flex items-center gap-2 border-l-2 border-transparent px-3 py-1.5 text-sm text-muted", isActive && "border-accent text-ink")}
              >
                <Icon className="size-4" aria-hidden="true" />
                {link.label}
              </NavLink>
            );
          })}
        </nav>
        <div className="mt-auto hidden space-y-3 px-3 py-3 text-xs text-muted lg:block">
          <button
            type="button"
            className="text-left text-accent"
            aria-label={t("language.switch")}
            onClick={() => setLocale(locale === "en" ? "zh" : "en")}
          >
            {locale === "en" ? "中文" : "English"}
          </button>
          <details>
            <summary className="cursor-pointer">{t(`status.${code === "checking" ? "checking" : code === "unavailable" ? "unavailable" : code === "missing" ? "keyMissing" : code === "unverified" ? "unverified" : code === "passed" ? "passed" : "failed"}`)}</summary>
            <p className="mt-2 leading-5">{auth.data?.validation.message ?? t("status.noCheck")}</p>
            <p className="mt-1">{t("status.lastCheck")}: {checked ? formatWhen(checked) : t("status.noCheck")}</p>
          </details>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-col gap-2 border-b border-line bg-paper px-3 py-2 lg:flex-row lg:items-center">
          <form onSubmit={search} className="flex w-full max-w-xs gap-2">
            <input
              name="ticker"
              aria-label={t("shell.ticker")}
              placeholder={t("shell.ticker")}
              className="num h-8 w-full border border-line bg-paper px-2 text-sm uppercase text-ink outline-none focus:border-accent"
            />
            <button type="submit" className="h-8 shrink-0 whitespace-nowrap bg-accent px-3 text-sm text-paper">{t("shell.open")}</button>
          </form>
          <div className="flex min-w-0 flex-1 gap-px overflow-x-auto">
            {watchlist.data?.items.map((item) => (
              <div key={item.ticker} className="flex shrink-0 items-stretch border border-line bg-paper">
                <button
                  type="button"
                  title={t("quote.notLive")}
                  onClick={() => navigate(`/research?ticker=${encodeURIComponent(item.ticker)}`)}
                  className="px-2 py-1 text-left"
                >
                  <div className="num text-xs">{item.ticker}</div>
                  <div className={cn("num text-[11px]", changeClass(item.change))}>{item.ok ? formatNumber(item.price ?? null) : t("quote.noPrice")}</div>
                  <div className="text-[10px] text-faint">{item.bar_date ?? t("common.unknown")}</div>
                </button>
                <button
                  type="button"
                  className="border-l border-line px-1.5 text-xs text-muted hover:text-danger"
                  aria-label={t("shell.removeWatch").replace("{ticker}", item.ticker)}
                  disabled={removeWatch.isPending}
                  onClick={() => removeWatch.mutate(item.ticker)}
                >
                  ×
                </button>
              </div>
            ))}
            {watchlist.isLoading && <span className="self-center px-2 text-xs text-faint">{t("common.loading")}</span>}
            {watchlist.isError && <span className="self-center px-2 text-xs text-danger">{watchlist.error.message}</span>}
            {removeWatch.isError && <span role="alert" className="self-center px-2 text-xs text-danger">{removeWatch.error.message}</span>}
          </div>
          <button
            type="button"
            className="h-8 w-fit self-start px-2 text-sm text-accent lg:hidden"
            aria-label={t("language.switch")}
            onClick={() => setLocale(locale === "en" ? "zh" : "en")}
          >
            {locale === "en" ? "中文" : "English"}
          </button>
        </header>
        <main className="min-w-0 flex-1 px-4 py-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function changeClass(change: number | null | undefined) {
  if (change === null || change === undefined) return "text-muted";
  return change >= 0 ? "text-ok" : "text-danger";
}
