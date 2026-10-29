import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { getLocale, interpolate, intlLocale, readLocale, setCurrentLocale, type Locale } from "./locale";
import { en, fr, type Messages } from "./messages";

function lookup(dict: Messages, key: string): string | undefined {
  const parts = key.split(".");
  let cur: any = dict;
  for (const p of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = cur[p];
  }
  return typeof cur === "string" ? cur : undefined;
}

export function translate(key: string, vars?: Record<string, string | number>, locale?: Locale): string {
  const loc = locale || getLocale();
  const dict = loc === "en" ? en : fr;
  const raw = lookup(dict, key);
  if (raw == null) return key;
  return interpolate(raw, vars);
}

type I18nCtx = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  intl: string;
};

const Ctx = createContext<I18nCtx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => (typeof window === "undefined" ? "fr" : readLocale()));

  const setLocale = useCallback((next: Locale) => {
    setCurrentLocale(next);
    import("../geo").then((g) => g.clearCountryCache()).catch(() => undefined);
    setLocaleState(next);
    window.dispatchEvent(new Event("tacite-locale"));
  }, []);

  const t = useCallback((key: string, vars?: Record<string, string | number>) => translate(key, vars, locale), [locale]);

  const value = useMemo<I18nCtx>(() => ({
    locale,
    setLocale,
    t,
    intl: intlLocale(locale),
  }), [locale, setLocale, t]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export function LanguageToggle() {
  const { locale, setLocale, t } = useI18n();
  const next = locale === "fr" ? "en" : "fr";
  return (
    <button
      type="button"
      onClick={() => setLocale(next)}
      title={t("lang.switch")}
      aria-label={t("lang.switch")}
      className="rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-faint transition-colors hover:bg-surface hover:text-ink"
    >
      {locale === "fr" ? "EN" : "FR"}
    </button>
  );
}
