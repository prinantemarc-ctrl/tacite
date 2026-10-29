export type Locale = "fr" | "en";

export const LOCALE_KEY = "tacite-locale";

export function readLocale(): Locale {
  try {
    const v = localStorage.getItem(LOCALE_KEY);
    if (v === "en" || v === "fr") return v;
  } catch { /* private mode */ }
  return "fr";
}

export function intlLocale(locale: Locale): string {
  return locale === "en" ? "en-US" : "fr-FR";
}

let current: Locale = typeof window === "undefined" ? "fr" : readLocale();

export function getLocale(): Locale {
  return current;
}

export function setCurrentLocale(locale: Locale) {
  current = locale;
  try { localStorage.setItem(LOCALE_KEY, locale); } catch { /* private mode */ }
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
    document.title = locale === "en" ? "Tacite — Press intelligence" : "Tacite — Intelligence presse";
  }
}

export function interpolate(tpl: string, vars?: Record<string, string | number>): string {
  if (!vars) return tpl;
  return tpl.replace(/\{(\w+)\}/g, (_, k) => (vars[k] == null ? `{${k}}` : String(vars[k])));
}
