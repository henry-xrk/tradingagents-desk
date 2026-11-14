import type { ReactNode } from "react";

import { useLocale } from "../i18n.tsx";
import { formatWhen } from "../lib/utils.ts";

const PHASES = [
  "queued",
  "analysts",
  "research_debate",
  "trader",
  "risk_debate",
  "portfolio_manager",
  "saving_report",
  "reports_ready",
  "completed",
  "failed",
  "timed_out",
] as const;

export function AgentWorkflow({
  phase,
  agentStatus,
  activity,
}: {
  phase: string;
  agentStatus: Record<string, string>;
  activity: { at: string; message: string }[];
}) {
  const { t } = useLocale();
  const agents = Object.entries(agentStatus);
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[11px] tracking-wide text-faint uppercase">{t("log.phase")}</div>
        <div className="mt-1 text-sm">{phaseLabel(t, phase)}</div>
        <p className="mt-1 text-xs text-muted">{t("log.noPercent")}</p>
      </div>
      <ol className="flex flex-wrap gap-1.5">
        {PHASES.filter((id) => !["failed", "timed_out"].includes(id) || id === phase).map((id) => (
          <li
            key={id}
            className={
              id === phase
                ? "rounded border border-accent bg-accent-soft px-2 py-1 text-xs text-accent"
                : "rounded border border-line px-2 py-1 text-xs text-faint"
            }
          >
            {phaseLabel(t, id)}
          </li>
        ))}
      </ol>
      <ul className="space-y-1.5">
        {agents.map(([name, status]) => (
          <li key={name} className="flex items-center justify-between gap-3 text-sm">
            <span>{agentLabel(t, name)}</span>
            <StatusDot status={status} label={statusLabel(t, status)} />
          </li>
        ))}
        {agents.length === 0 && <li className="text-sm text-muted">{t("log.noRun")}</li>}
      </ul>
      <div>
        <div className="mb-1 text-[11px] tracking-wide text-faint uppercase">{t("log.activity")}</div>
        <ul className="space-y-1 font-mono text-[11px] text-muted">
          {activity.slice(-8).map((item, index) => (
            <li key={`${item.at}-${index}`}>{formatWhen(item.at)} · {item.message}</li>
          ))}
          {activity.length === 0 && <li>{t("log.noEvents")}</li>}
        </ul>
      </div>
    </div>
  );
}

function phaseLabel(t: (key: string) => string, phase: string) {
  const key = `phase.${phase}`;
  const value = t(key);
  return value === key ? phase.replaceAll("_", " ") : value;
}

function agentLabel(t: (key: string) => string, name: string) {
  const key = `agent.${name}`;
  const value = t(key);
  return value === key ? name : value;
}

function statusLabel(t: (key: string) => string, status: string) {
  const key = `log.${status}`;
  const value = t(key);
  return value === key ? status.replaceAll("_", " ") : value;
}

function StatusDot({ status, label }: { status: string; label: string }) {
  const color = status === "completed" ? "bg-ok" : status === "in_progress" ? "bg-warn" : status === "failed" ? "bg-danger" : "bg-faint";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-muted">
      <span className={`size-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="border border-line bg-paper">
      <header className="flex items-center justify-between gap-3 border-b border-line px-3 py-1.5">
        <h2 className="text-[11px] font-medium tracking-wide text-faint uppercase">{title}</h2>
        {action}
      </header>
      <div className="px-3 py-2">{children}</div>
    </section>
  );
}
