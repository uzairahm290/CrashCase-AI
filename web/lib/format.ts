import type { ClaimStatus } from "./api";

const pkr = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 });

/** Rounded to the nearest 100 rupees: 128,437 -> "128,400". */
export const money = (v: number) => pkr.format(Math.round(v / 100) * 100);

export const moneyShort = (v: number) =>
  v >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : v >= 1000 ? `${Math.round(v / 1000)}k` : `${v}`;

export const label = (s: string) => s.replace(/_/g, " ");

export const pct = (v: number) => `${Math.round(v * 100)}%`;

export const shortId = (id: string) => id.slice(0, 8).toUpperCase();

export function when(iso: string) {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export const STATUS_TEXT: Record<ClaimStatus, string> = {
  queued: "Waiting",
  processing: "Assessing",
  rejected: "Photos rejected",
  done: "Needs review",
  failed: "Failed",
  approved: "Approved",
  declined: "Declined",
};

export const CAR_TEXT: Record<string, string> = { hatchback: "Hatchback", sedan: "Sedan", suv: "SUV" };

/** "Glass shatter" from "glass_shatter". */
export const sentence = (s: string) => label(s).replace(/^\w/, (c) => c.toUpperCase());

export const ordinal = (n: number) => ["closest", "2nd closest", "3rd closest"][n] ?? `${n + 1}th closest`;
