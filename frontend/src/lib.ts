export function formatMoney(amount: string | number, currency: string): string {
  const n = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(n)) return `${currency} 0.00`;
  return `${currency} ${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
}

export function pct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}
