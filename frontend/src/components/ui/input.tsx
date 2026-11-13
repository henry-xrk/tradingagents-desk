import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";

import { cn } from "../../lib/utils.ts";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-9 w-full rounded-md border border-[#b7c4d0] bg-white px-3 text-sm text-[#1a2330] outline-none placeholder:text-[#6b7c8d] focus:border-[#1a56a8]",
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
        "h-9 w-full rounded-md border border-[#b7c4d0] bg-white px-2 text-sm text-[#1a2330] outline-none focus:border-[#1a56a8]",
        className,
      )}
      {...props}
    />
  );
}
