/**
 * Exact decimal-string formatting.
 *
 * The API sends money as decimal strings. Every total, delta and percentage in
 * the UI is formatted from those strings with integer (BigInt) arithmetic, so
 * no displayed amount is ever derived from a binary float. The only float
 * conversion is inside `compactMoney`, which feeds chart axes and is explicitly
 * labelled as approximate.
 */

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;

function split(value: string): { negative: boolean; int: string; frac: string } | null {
  const match = DECIMAL.exec(value.trim());
  if (!match) return null;
  return {
    negative: match[1] === "-",
    int: match[2].replace(/^0+(?=\d)/, ""),
    frac: match[3] ?? "",
  };
}

export function isDecimal(value: string | null | undefined): boolean {
  return typeof value === "string" && DECIMAL.test(value.trim());
}

function group(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Format a decimal string with fixed display precision, half-up rounding. */
export function formatDecimal(
  value: string | null | undefined,
  dp = 2,
  options: { group?: boolean } = {},
): string {
  if (value === null || value === undefined || value === "") return "—";
  const parts = split(value);
  if (!parts) return value;
  const { negative, int, frac } = parts;

  let digits = BigInt(int + frac.padEnd(dp, "0"));
  if (frac.length > dp) {
    digits = BigInt(int + frac.slice(0, dp).padEnd(dp, "0"));
    if (Number(frac[dp] ?? "0") >= 5) digits += 1n;
  }

  const padded = digits.toString().padStart(dp + 1, "0");
  const intPart = padded.slice(0, padded.length - dp) || "0";
  const fracPart = dp > 0 ? padded.slice(padded.length - dp) : "";
  const isZero = digits === 0n;
  const sign = negative && !isZero ? "-" : "";
  const shown = options.group === false ? intPart : group(intPart);
  return `${sign}${shown}${dp > 0 ? `.${fracPart}` : ""}`;
}

export function formatMoney(value: string | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const formatted = formatDecimal(value, 2);
  return currency ? `${formatted} ${currency}` : formatted;
}

export function formatPercent(value: string | null | undefined, dp = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  return `${formatDecimal(value, dp)}%`;
}

/** Format a ratio decimal string ("0.90") as a percentage ("90%"). */
export function formatRatioPercent(value: string | null | undefined, dp = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const percent = fromScaled(toScaled(value) * 100n);
  return formatPercent(percent, dp);
}

/** Decimal string -> integer scaled by 10^scale, rounded half-up. */
export function toScaled(value: string, scale = 6): bigint {
  const parts = split(value);
  if (!parts) throw new Error(`Not a decimal string: ${value}`);
  const frac = parts.frac;
  let digits = BigInt(parts.int + frac.padEnd(scale, "0").slice(0, scale));
  if (frac.length > scale && Number(frac[scale] ?? "0") >= 5) digits += 1n;
  return parts.negative ? -digits : digits;
}

export function fromScaled(scaled: bigint, scale = 6): string {
  const negative = scaled < 0n;
  const text = (negative ? -scaled : scaled).toString().padStart(scale + 1, "0");
  const int = text.slice(0, text.length - scale) || "0";
  const frac = scale > 0 ? text.slice(text.length - scale) : "";
  return `${negative ? "-" : ""}${int}${scale > 0 ? `.${frac}` : ""}`;
}

export function addDecimal(a: string, b: string, scale = 6): string {
  return fromScaled(toScaled(a, scale) + toScaled(b, scale), scale);
}

export function subtractDecimal(a: string, b: string, scale = 6): string {
  return fromScaled(toScaled(a, scale) - toScaled(b, scale), scale);
}

export function sumDecimals(values: string[], scale = 6): string {
  return fromScaled(
    values.reduce((total, value) => total + toScaled(value, scale), 0n),
    scale,
  );
}

/** Percentage change with two decimals, half away from zero. Null if base is 0. */
export function percentChange(previous: string, current: string): string | null {
  const base = toScaled(previous);
  if (base === 0n) return null;
  const diff = toScaled(current) - base;
  const numerator = diff * 10_000n;
  let basisPoints = numerator / base;
  const remainder = numerator % base;
  if (remainder !== 0n && (remainder < 0n ? -remainder : remainder) * 2n >= (base < 0n ? -base : base)) {
    basisPoints += numerator < 0n ? -1n : 1n;
  }
  const negative = basisPoints < 0n;
  const abs = negative ? -basisPoints : basisPoints;
  const int = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "−" : "+"}${group(int.toString())}.${frac}%`;
}

/**
 * Approximate compact value for a chart axis only.
 * Never use this for a displayed total, delta or export.
 */
export function compactMoney(value: string, currency?: string | null): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  const formatter = new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  return currency ? `${formatter.format(amount)} ${currency}` : formatter.format(amount);
}

/** Chart plotting value. Approximate by design; see compactMoney. */
export function plotValue(value: string): number {
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : 0;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return value;
  const seconds = Math.round((then - Date.now()) / 1000);
  const absolute = Math.abs(seconds);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (absolute < 60) return formatter.format(seconds, "second");
  if (absolute < 3_600) return formatter.format(Math.round(seconds / 60), "minute");
  if (absolute < 86_400) return formatter.format(Math.round(seconds / 3_600), "hour");
  return formatter.format(Math.round(seconds / 86_400), "day");
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
