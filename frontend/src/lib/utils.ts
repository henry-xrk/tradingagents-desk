import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatShares(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Unavailable";
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function formatWhen(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function parseOptionalNumber(value: string): number | null {
  const text = value.trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

export function parsePriceList(value: string): number[] {
  const prices: number[] = [];
  for (const part of value.split(",")) {
    const number = Number(part.trim());
    if (Number.isFinite(number) && number > 0 && !prices.includes(number)) prices.push(number);
  }
  return prices;
}

export function priceList(values: number[] | null | undefined): string {
  return (values ?? []).join(", ");
}
