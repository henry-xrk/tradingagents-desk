import { useLocale } from "../i18n.tsx";
import { MarkdownView } from "./MarkdownView.tsx";
import { Badge } from "./ui/badge.tsx";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs.tsx";

const SECTIONS = [
  "market_report",
  "sentiment_report",
  "news_report",
  "fundamentals_report",
  "bull_history",
  "bear_history",
  "investment_plan",
  "trader_investment_plan",
  "aggressive_history",
  "conservative_history",
  "neutral_history",
  "final_trade_decision",
] as const;

export function ReportTabs({ reports }: { reports: Record<string, string> | undefined }) {
  const { t } = useLocale();
  const available = SECTIONS.filter((key) => reports?.[key]);
  if (available.length === 0) {
    return <p className="text-sm text-muted">{t("report.empty")}</p>;
  }
  return (
    <Tabs defaultValue={available[0][0]}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <Badge>{t("report.generated")}</Badge>
      </div>
      <TabsList aria-label={t("report.sections")}>
        {available.map((key) => (
          <TabsTrigger key={key} value={key}>
            {t(`section.${key}`)}
          </TabsTrigger>
        ))}
      </TabsList>
      {available.map((key) => (
        <TabsContent key={key} value={key}>
          <MarkdownView text={reports?.[key] ?? ""} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
