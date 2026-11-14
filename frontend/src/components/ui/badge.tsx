import type { HTMLAttributes } from "react";

import { cn } from "../../lib/utils.ts";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border border-line-strong px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted uppercase",
        className,
      )}
      {...props}
    />
  );
}
