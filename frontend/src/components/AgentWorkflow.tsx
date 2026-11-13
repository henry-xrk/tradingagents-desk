import type { ReactNode } from "react";

const PHASES = [
  ["queued", "Queued"],
  ["analysts", "Analysts"],
  ["research_debate", "Research debate"],
  ["trader", "Trader"],
  ["risk_debate", "Risk debate"],
  ["portfolio_manager", "Portfolio manager"],
  ["saving_report", "Saving report"],
  ["reports_ready", "Reports ready"],
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["timed_out", "Timed out"],
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
  const agents = Object.entries(agentStatus);
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[11px] tracking-wide text-[#6b7c8d] uppercase">Current phase</div>
        <div className="mt-1 text-sm">{labelFor(phase)}</div>
        <p className="mt-1 text-xs text-[#4d5d6d]">
          Status changes when a report section arrives. There is no completion percentage.
        </p>
      </div>
      <ol className="flex flex-wrap gap-1.5">
        {PHASES.filter(([id]) => !["failed", "timed_out"].includes(id) || id === phase).map(([id, label]) => (
          <li
            key={id}
            className={
              id === phase
                ? "rounded border border-[#1a56a8] px-2 py-1 text-[11px] text-[#1a56a8]"
                : "rounded border border-[#d5dee6] px-2 py-1 text-[11px] text-[#6b7c8d]"
            }
          >
            {label}
          </li>
        ))}
      </ol>
      <ul className="space-y-1.5">
        {agents.map(([name, status]) => (
          <li key={name} className="flex items-center justify-between gap-3 text-sm">
            <span>{name}</span>
            <StatusDot status={status} />
          </li>
        ))}
        {agents.length === 0 && <li className="text-sm text-[#4d5d6d]">No run selected.</li>}
      </ul>
      <div>
        <div className="mb-1 text-[11px] tracking-wide text-[#6b7c8d] uppercase">Activity</div>
        <ul className="space-y-1 font-mono text-[11px] text-[#4d5d6d]">
          {activity.slice(-6).map((item, index) => (
            <li key={`${item.at}-${index}`}>{item.message}</li>
          ))}
          {activity.length === 0 && <li>No events yet.</li>}
        </ul>
      </div>
    </div>
  );
}

function labelFor(phase: string) {
  return PHASES.find(([id]) => id === phase)?.[1] ?? phase;
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "completed" ? "bg-[#0c7a43]" : status === "in_progress" ? "bg-[#8a5a00]" : status === "failed" ? "bg-[#c4233c]" : "bg-[#9aabba]";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-[#4d5d6d]">
      <span className={`size-1.5 rounded-full ${color}`} />
      {status.replace("_", " ")}
    </span>
  );
}

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[#d5dee6] bg-[#ffffff]">
      <header className="flex items-center justify-between gap-3 border-b border-[#d5dee6] px-4 py-3">
        <h2 className="text-sm font-medium">{title}</h2>
        {action}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}
