import { createContext, useContext, useState, type ReactNode } from "react";
import type { Currency } from "./types";

interface CurrencyCtx {
  currency: Currency;
  setCurrency: (c: Currency) => void;
}

const Ctx = createContext<CurrencyCtx>(null as unknown as CurrencyCtx);

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [currency, setCurrencyState] = useState<Currency>(() => {
    const saved = localStorage.getItem("cp_currency");
    return saved === "USD" || saved === "EUR" || saved === "INR" ? saved : "USD";
  });

  const setCurrency = (c: Currency) => {
    localStorage.setItem("cp_currency", c);
    setCurrencyState(c);
  };

  return <Ctx.Provider value={{ currency, setCurrency }}>{children}</Ctx.Provider>;
}

export function useCurrency(): CurrencyCtx {
  return useContext(Ctx);
}
