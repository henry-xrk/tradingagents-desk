import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";

import { cn } from "../../lib/utils.ts";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-md border border-line-strong bg-paper px-3 text-sm text-ink outline-none placeholder:text-faint focus:border-accent",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 w-full rounded-md border border-line-strong bg-paper px-2 text-sm text-ink outline-none focus:border-accent",
        className,
      )}
      {...props}
    />
  );
}
