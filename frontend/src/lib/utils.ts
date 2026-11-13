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

export function numberError(
  value: string,
  label: string,
  options?: { min?: number; max?: number; allowEmpty?: boolean },
): string | null {
  const text = value.trim();
  if (!text) return options?.allowEmpty === false ? `${label} is required.` : null;
  const number = Number(text);
  if (!Number.isFinite(number)) return `${label} must be a finite number.`;
  if (options?.min !== undefined && number < options.min) return `${label} must be at least ${options.min}.`;
  if (options?.max !== undefined && number > options.max) return `${label} must be at most ${options.max}.`;
  return null;
}

export function priceListError(value: string): string | null {
  if (!value.trim()) return null;
  for (const part of value.split(",")) {
    const text = part.trim();
    if (!text) continue;
    const number = Number(text);
    if (!Number.isFinite(number) || number <= 0) return `"${text}" must be a positive finite price.`;
  }
  return null;
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
