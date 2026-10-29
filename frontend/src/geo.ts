/** Utilitaires pays — ISO 3166-1 alpha-2 → drapeau, nom localisé. Liste officielle via /api/countries. */

import { getLocale } from "./i18n/locale";
import { translate } from "./i18n/I18nProvider";

export const FR_AXIS_ZONE = new Set(["FR", "BE", "CH", "LU"]);
export const FR_SPECIFIC_AXES = new Set(["secularism", "institutions"]);

export function flag(code?: string | null): string {
  if (!code || code.length !== 2) return "";
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 127397 + c.charCodeAt(0)));
}

function regionDisplay() {
  return typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames([getLocale()], { type: "region" })
    : null;
}

export function countryName(code?: string | null): string {
  if (!code) return "—";
  try {
    return regionDisplay()?.of(code.toUpperCase()) || code;
  } catch {
    return code;
  }
}

function langDisplay() {
  return typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames([getLocale()], { type: "language" })
    : null;
}

export function languageName(code?: string | null): string {
  if (!code) return "—";
  try {
    return langDisplay()?.of(code) || code;
  } catch {
    return code;
  }
}

let isoCache: { code: string; name: string }[] | null = null;

/** Liste ISO servie par l'API (plus de balayage AA–ZZ). */
export async function loadIsoCountries(): Promise<{ code: string; name: string }[]> {
  if (isoCache) return isoCache;
  const { listCountries } = await import("./api");
  const rows = await listCountries(true);
  isoCache = rows
    .map((r: any) => ({ code: r.code, name: countryName(r.code) }))
    .sort((a, b) => a.name.localeCompare(b.name, getLocale()));
  return isoCache;
}

export const AXIS_LABELS_FR: Record<string, string> = {
  economy: "Économie", society: "Société", immigration: "Immigration", europe: "Europe",
  ecology: "Écologie", security: "Sécurité", secularism: "Laïcité", international: "International",
  institutions: "Institutions", media: "Médias", justice: "Justice", technology: "Technologie",
};

export function axisLabel(axis: string): string {
  const tr = translate(`axis.${axis}`);
  return tr !== `axis.${axis}` ? tr : (AXIS_LABELS_FR[axis] || axis);
}

export function clearCountryCache() {
  isoCache = null;
}

export function maxUsableGapInfo(o: any): { axis: string; label: string; value: number } | null {
  if (o?.max_gap && typeof o.max_gap.value === "number" && Number.isFinite(o.max_gap.value)) {
    return {
      axis: o.max_gap.axis,
      label: axisLabel(o.max_gap.axis) || o.max_gap.label || o.max_gap.axis,
      value: o.max_gap.value,
    };
  }
  const gaps = o?.latest_profile?.gap_from_official;
  if (!gaps) return null;
  const n = o.latest_profile?.axis_n || {};
  const hasN = n && Object.keys(n).length > 0;
  const skipFr = !FR_AXIS_ZONE.has((o.country || "").toUpperCase());
  const entries = Object.entries(gaps).filter(([k]) => {
    if (skipFr && FR_SPECIFIC_AXES.has(k)) return false;
    if (hasN && (Number(n[k]) || 0) < 10) return false;
    return true;
  }) as [string, number][];
  if (!entries.length) return null;
  const [axis, value] = entries.reduce((best, cur) => (Math.abs(Number(cur[1]) || 0) > Math.abs(Number(best[1]) || 0) ? cur : best));
  return { axis, label: axisLabel(axis), value: Number(value) || 0 };
}

export function maxUsableGap(o: any): number | null {
  return maxUsableGapInfo(o)?.value ?? null;
}
