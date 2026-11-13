import { MarkdownView } from "./MarkdownView.tsx";
import { Badge } from "./ui/badge.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs.tsx";

const SECTIONS = [
  ["market_report", "Market"],
  ["sentiment_report", "Sentiment"],
  ["news_report", "News"],
  ["fundamentals_report", "Fundamentals"],
  ["bull_history", "Bull"],
  ["bear_history", "Bear"],
  ["investment_plan", "Research plan"],
  ["trader_investment_plan", "Trader"],
  ["aggressive_history", "Aggressive risk"],
  ["conservative_history", "Conservative risk"],
  ["neutral_history", "Neutral risk"],
  ["final_trade_decision", "Decision"],
] as const;

export function ReportTabs({ reports }: { reports: Record<string, string> | undefined }) {
  const available = SECTIONS.filter(([key]) => reports?.[key]);
  if (available.length === 0) {
    return <p className="text-sm text-[#4d5d6d]">Report sections appear here as the agents file them.</p>;
  }
  return (
    <Tabs defaultValue={available[0][0]}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <Badge className="border-[#c4a15a] text-[#8a5a00]">Generated research</Badge>
      </div>
      <TabsList>
        {available.map(([key, label]) => (
          <TabsTrigger key={key} value={key}>
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      {available.map(([key]) => (
        <TabsContent key={key} value={key}>
          <MarkdownView text={reports?.[key] ?? ""} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
