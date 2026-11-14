import type { ReactNode } from "react";

import { cn } from "../lib/utils.ts";

const tones = {
  neutral: "text-muted before:bg-faint",
  ok: "text-ok before:bg-ok",
  warn: "text-warn before:bg-warn",
  danger: "text-danger before:bg-danger",
};

export function StatusText({ tone = "neutral", children, className }: { tone?: keyof typeof tones; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs before:inline-block before:size-1.5 before:rounded-full before:content-['']", tones[tone], className)}>
      {children}
    </span>
  );
}

const ratingTones = {
  Underweight: "bg-warn-soft text-warn",
  Overweight: "bg-ok-soft text-ok",
  Hold: "bg-canvas text-muted",
};

export function RatingMark({ rating, unknown }: { rating: string | null | undefined; unknown: string }) {
  const text = rating && rating !== "REVIEW" ? rating : unknown;
  const tone = ratingTones[text as keyof typeof ratingTones] ?? "bg-canvas text-muted";
  return <span className={cn("inline-flex items-center px-1.5 py-0.5 text-xs font-medium", tone)}>{text}</span>;
}
