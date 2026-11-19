import { describe, expect, it } from "vitest";

import {
  addDecimal,
  compactMoney,
  formatDecimal,
  formatMoney,
  formatPercent,
  formatRatioPercent,
  fromScaled,
  percentChange,
  plotValue,
  sumDecimals,
  toScaled,
} from "./money";

describe("formatDecimal", () => {
  it("rounds half up from the decimal string, not a binary float", () => {
    expect(formatDecimal("1.005", 2)).toBe("1.01");
    expect(formatDecimal("2.675", 2)).toBe("2.68");
    expect(formatDecimal("-1.005", 2)).toBe("-1.01");
    expect(formatDecimal("0.004", 2)).toBe("0.00");
  });

  it("groups thousands and keeps the sign only for non-zero values", () => {
    expect(formatDecimal("1234567.891", 2)).toBe("1,234,567.89");
    expect(formatDecimal("-0.000", 2)).toBe("0.00");
    expect(formatDecimal("12", 0)).toBe("12");
  });

  it("returns an em dash for missing values and passes unknown text through", () => {
    expect(formatDecimal(null)).toBe("—");
    expect(formatDecimal("not-a-number")).toBe("not-a-number");
  });
});

describe("exact money helpers", () => {
  it("never leaks binary float artefacts", () => {
    expect(addDecimal("0.1", "0.2")).toBe("0.300000");
    expect(sumDecimals(["276.720019", "0.000001"])).toBe("276.720020");
    expect(sumDecimals(["0.000000", "-1.500000"])).toBe("-1.500000");
  });

  it("round-trips scaled integers", () => {
    expect(fromScaled(toScaled("123.456789"))).toBe("123.456789");
    expect(toScaled("-0.000001")).toBe(-1n);
    expect(toScaled("1.9999995")).toBe(2_000_000n);
  });

  it("formats money with an explicit currency and no symbol guessing", () => {
    expect(formatMoney("1531.305850", "USD")).toBe("1,531.31 USD");
    expect(formatMoney("4.552105", "EUR")).toBe("4.55 EUR");
    expect(formatMoney(null, "USD")).toBe("—");
  });

  it("formats ratio decimals as percentages without showing 0.9 as 1%", () => {
    expect(formatRatioPercent("0.90", 0)).toBe("90%");
    expect(formatRatioPercent("0.995", 1)).toBe("99.5%");
    expect(formatRatioPercent(null)).toBe("—");
  });

  it("computes signed percentage change with exact decimals", () => {
    expect(percentChange("100.00", "112.50")).toBe("+12.50%");
    expect(percentChange("100.00", "90.00")).toBe("−10.00%");
    expect(percentChange("100.00", "100.00")).toBe("+0.00%");
    expect(percentChange("0", "10")).toBeNull();
  });

  it("formats percentages from decimal strings", () => {
    expect(formatPercent("12.3456", 2)).toBe("12.35%");
    expect(formatPercent("58.540", 1)).toBe("58.5%");
    expect(formatPercent(null)).toBe("—");
  });
});

describe("chart-only approximations", () => {
  it("converts for plotting and degrades safely", () => {
    expect(plotValue("12.5")).toBe(12.5);
    expect(plotValue("not-a-number")).toBe(0);
  });

  it("labels compact values with the currency", () => {
    expect(compactMoney("1531.30585", "USD")).toMatch(/ USD$/);
    expect(compactMoney("1531.30585")).not.toContain("USD");
  });
});
