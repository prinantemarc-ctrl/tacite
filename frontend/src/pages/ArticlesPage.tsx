import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search, X } from "lucide-react";
import { listArticles, searchArticles, listOutlets } from "../api";
import { Card, Badge, Button, Input, Select, PageHeader, Empty, Loading, Term } from "../components";
import { flag, countryName } from "../geo";
import { useI18n } from "../i18n/I18nProvider";

const STATUS_TONE: Record<string, "default" | "accent" | "faint" | "alert"> = {
  analyzed: "accent",
  embedded_only: "faint",
  pending: "default",
  failed: "alert",
  error: "alert",
  duplicate: "faint",
};

function statusKey(s: string) {
  return s === "failed" ? "error" : s;
}

export default function ArticlesPage() {
  const { t, intl, locale } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [articles, setArticles] = useState<any[]>([]);
  const [outlets, setOutlets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [countryFilter, setCountryFilter] = useState(searchParams.get("country") || "");
  const [outletFilter, setOutletFilter] = useState(searchParams.get("outlet_id") || "");
  const [statusFilter, setStatusFilter] = useState(searchParams.get("status") || "");
  const [mode, setMode] = useState<"latest" | "search">("latest");

  useEffect(() => { listOutlets().then(setOutlets); }, []);

  useEffect(() => {
    const next: Record<string, string> = {};
    if (countryFilter) next.country = countryFilter;
    if (outletFilter) next.outlet_id = outletFilter;
    if (statusFilter) next.status = statusFilter;
    setSearchParams(next, { replace: true });
  }, [countryFilter, outletFilter, statusFilter, setSearchParams]);

  useEffect(() => {
    if (mode !== "latest") return;
    setLoading(true);
    listArticles([
      countryFilter && `country=${countryFilter}`,
      outletFilter && `outlet_id=${outletFilter}`,
      statusFilter && `status=${statusFilter}`,
      "limit=100",
    ].filter(Boolean).join("&")).then(setArticles).finally(() => setLoading(false));
  }, [countryFilter, outletFilter, statusFilter, mode]);

  const present = useMemo(
    () => [...new Set(outlets.map((o: any) => o.country).filter(Boolean))].sort((a, b) => countryName(a).localeCompare(countryName(b), locale)),
    [outlets, locale],
  );
  const outletsForSelect = countryFilter ? outlets.filter((o: any) => o.country === countryFilter) : outlets;

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try { setArticles(await searchArticles(query)); setMode("search"); } finally { setSearching(false); }
  };
  const reset = () => { setQuery(""); setCountryFilter(""); setOutletFilter(""); setStatusFilter(""); setMode("latest"); };
  const outletMap = Object.fromEntries(outlets.map((o: any) => [o.id, o]));
  const pickCountry = (code: string) => {
    setCountryFilter(code);
    if (code && outletFilter) {
      const o = outlets.find((x: any) => String(x.id) === String(outletFilter));
      if (o && o.country !== code) setOutletFilter("");
    }
    setMode("latest");
  };

  const statusLabel = (raw: string) => {
    const key = statusKey(raw || "pending");
    const label = t(`status.${key}`);
    return label === `status.${key}` ? t("status.pending") : label;
  };

  return (
    <div>
      <PageHeader
        kicker={t("nav.kArticles")}
        title={t("pages.articles")}
        subtitle={mode === "search" ? t("articles.searchResults", { n: articles.length, s: articles.length > 1 ? "s" : "", query }) : <>{t("articles.latest", { n: articles.length })}{countryFilter ? ` · ${flag(countryFilter)} ${countryName(countryFilter)}` : ""}. {t("articles.statuses")} <Term k="status_analyzed">{t("status.analyzed")}</Term> · <Term k="status_embedded">{t("status.embedded_only")}</Term> · <Term k="status_duplicate">{t("status.duplicate")}</Term> · <Term k="status_pending">{t("status.pending")}</Term>.</>}
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[280px]">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSearch()} placeholder={t("articles.searchPlaceholder")} className="pl-8" />
        </div>
        <Button variant="primary" onClick={handleSearch} disabled={searching || !query.trim()}>{searching ? "…" : t("articles.searchAction")}</Button>
        <Select value={countryFilter} onChange={(e) => pickCountry(e.target.value)}>
          <option value="">{t("common.allCountries")}</option>
          {present.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
        </Select>
        <Select value={outletFilter} onChange={(e) => { setOutletFilter(e.target.value); setMode("latest"); }}>
          <option value="">{t("common.allOutlets")}</option>
          {countryFilter
            ? outletsForSelect.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)
            : present.map((c) => (
              <optgroup key={c} label={`${flag(c)} ${countryName(c)}`}>
                {outlets.filter((o: any) => o.country === c).map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </optgroup>
            ))}
        </Select>
        <Select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setMode("latest"); }}>
          <option value="">{t("articles.allStatuses")}</option>
          <option value="analyzed">{t("status.analyzed")}</option>
          <option value="pending">{t("status.pending")}</option>
          <option value="embedded_only">{t("status.embedded_only")}</option>
          <option value="duplicate">{t("status.duplicate")}</option>
          <option value="error">{t("status.error")}</option>
        </Select>
        {(mode === "search" || countryFilter || outletFilter || statusFilter) && <Button variant="ghost" onClick={reset}><X size={13} /> {t("articles.reset")}</Button>}
      </div>

      <Card>
        {loading ? <Loading /> : articles.length === 0 ? <Empty>{t("articles.empty")}</Empty> : (
          <ol className="divide-y divide-hair-soft">
            {articles.map((a) => {
              const d = a.extracted_data || {};
              const o = outletMap[a.outlet_id];
              const tone = STATUS_TONE[a.analysis_status] || STATUS_TONE.pending;
              return (
                <li key={a.id} className="grid gap-x-6 gap-y-1 py-3 first:pt-0 last:pb-0 md:grid-cols-[1fr_auto]">
                  <div className="min-w-0">
                    <Link to={`/articles/${a.id}`} className="text-[13.5px] font-medium leading-snug text-ink hover:text-accent-strong">{a.title}</Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-faint">
                      <Link to={`/outlets/${a.outlet_id}`} className="text-muted hover:text-accent-strong">{flag(o?.country)} {o?.name || a.outlet_name || t("articles.outletFallback", { id: a.outlet_id })}</Link>
                      {(a.authors?.length ? a.authors : a.journalist_name ? [{ id: a.journalist_id, name: a.journalist_name }] : []).map((j: any, i: number) => (
                        <span key={j.id || i}>{i === 0 ? <span>·</span> : ","} {j.id ? <Link to={`/journalists/${j.id}`} className="hover:text-accent-strong">{j.name}</Link> : j.name}</span>
                      ))}
                      <span>·</span><span className="num">{new Date(a.published_at).toLocaleDateString(intl, { day: "2-digit", month: "short", year: "numeric" })}</span>
                      {a.language && <><span>·</span><span className="uppercase">{a.language}</span></>}
                    </div>
                    {a.text && <p className="mt-1 line-clamp-2 max-w-3xl text-[12px] text-muted">{a.text.slice(0, 260)}</p>}
                  </div>
                  <div className="flex flex-wrap content-start items-start gap-1 md:max-w-[260px] md:justify-end">
                    {a.similarity !== undefined && <Badge tone="ink">{(a.similarity * 100).toFixed(0)} %</Badge>}
                    <Badge tone={tone}>{statusLabel(a.analysis_status)}</Badge>
                    {d.topics?.slice(0, 2).map((topic: any, i: number) => <Badge key={i} tone="accent">{topic.label}</Badge>)}
                    {d.tone && <Badge>{d.tone}</Badge>}
                    {d.angle && <Badge tone="faint">{d.angle}</Badge>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Card>
    </div>
  );
}
