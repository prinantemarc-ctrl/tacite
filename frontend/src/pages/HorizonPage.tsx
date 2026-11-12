import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowUpRight, CheckCircle2, RefreshCw, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { createConversation, getHorizon } from "../api";
import { Badge, Empty, Loading, Segmented } from "../components";
import HorizonMap, { type HorizonArc, type HorizonCountry } from "../components/maps/HorizonMap";
import { countryName, flag } from "../geo";
import { useI18n } from "../i18n/I18nProvider";

type Layer = "all" | "signals" | "blocs" | "economy";
type Lang = { fr: string; en: string };
type ScenarioItem = { name: string; desc: string };
type SignpostBag = { confirm: string; abort: string };

type Forecast = {
  id: string;
  kind: "conflict" | "coalition" | "rapprochement" | "economy" | "signal" | "probe";
  chance: "likely" | "possible" | "unlikely";
  horizon_days: number;
  delay?: Lang;
  countries: string[];
  press_countries?: string[];
  languages?: string[];
  organizations?: string[];
  ruptures?: { outlet: string; country: string; axis: string; shift: number }[];
  title?: Lang;
  line?: Lang;
  blocks?: { forecast: Lang; dynamic: Lang; stake: Lang };
  scenarios?: { fr: ScenarioItem[]; en: ScenarioItem[] };
  signposts?: { fr: SignpostBag; en: SignpostBag };
  evidence: { id: number; title: string; outlet: string; country?: string; date: string }[];
};

type Payload = {
  as_of: string | null;
  min: string | null;
  max: string | null;
  countries: HorizonCountry[];
  arcs: HorizonArc[];
  signals: { dossier_id?: string; countries: string[] }[];
  blocs: { id: string; countries: string[]; label?: Lang }[];
  chokepoints: { id: string; choke_id?: string; name: Lang | string; lat: number; lon: number; delay?: Lang }[];
  forecasts: Forecast[];
  overview?: Lang;
  empty?: boolean;
};

const KIND_ACCENT: Record<string, string> = {
  conflict: "#c45c56",
  coalition: "#3d7a62",
  rapprochement: "#3d7a62",
  economy: "#d4a24c",
  signal: "#c4ae62",
  probe: "#c4ae62",
};

function prose(bag: Lang | undefined, locale: string) {
  if (!bag) return "";
  return locale === "en" ? bag.en : bag.fr;
}

function dayIndex(iso: string) {
  return Math.floor(new Date(iso + "T00:00:00Z").getTime() / 86400000);
}

export default function HorizonPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [mode, setMode] = useState<"flat" | "globe">("globe");
  const [layer, setLayer] = useState<Layer>("all");
  const [reading, setReading] = useState<"situation" | "forecast">("forecast");
  const [selected, setSelected] = useState<string | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);

  const bounds = data?.min && data?.max ? { min: dayIndex(data.min), max: dayIndex(data.max) } : null;
  const futureMax = bounds ? bounds.max + 60 : null;
  const lookingAhead = bounds != null && cursor != null && cursor > bounds.max;

  const loadHorizon = (asOf?: string, forceRefresh = false) => {
    if (forceRefresh) setRefreshing(true);
    else setLoading(true);
    getHorizon(asOf, forceRefresh)
      .then((d) => {
        setData(d);
        setError(null);
        if (cursor == null && d.max) setCursor(dayIndex(d.max));
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    const asOf =
      cursor != null && bounds && cursor <= bounds.max
        ? new Date(cursor * 86400000).toISOString().slice(0, 10)
        : undefined;
    loadHorizon(asOf, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor == null ? "live" : lookingAhead ? "ahead" : cursor]);

  const shown = useMemo(() => {
    const all = data?.forecasts || [];
    if (layer === "signals") return all.filter((f) => f.kind === "signal" || f.kind === "probe");
    if (layer === "blocs") return all.filter((f) => f.kind === "coalition" || f.kind === "rapprochement");
    if (layer === "economy") return all.filter((f) => f.kind === "economy");
    return all;
  }, [data, layer]);

  const activeDossier = useMemo(() => {
    if (!selected || !data?.forecasts) return null;
    return (
      data.forecasts.find((f) => f.id === selected) ||
      data.forecasts.find((f) => f.countries?.includes(selected)) ||
      null
    );
  }, [data, selected]);

  const pulses = useMemo(() => (data?.signals || []).flatMap((s) => s.countries), [data]);
  const blocsForMap = useMemo(
    () =>
      (data?.blocs || []).map((b) => ({
        id: b.id,
        countries: b.countries,
        label: b.label ? prose(b.label, locale) : undefined,
      })),
    [data, locale],
  );

  const headline = prose(data?.overview, locale);

  const openInAssistant = async (f: Forecast) => {
    const title = prose(f.title, locale) || prose(f.line, locale).slice(0, 60);
    try {
      const conv = await createConversation({
        title: `Horizon · ${title}`,
        context: { page: "/horizon", label: title },
      });
      navigate(`/assistant/${conv.id}`);
    } catch {
      navigate("/assistant");
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Barre supérieure Salle de Situation */}
      <div className="flex flex-wrap items-center gap-3 border-b border-hair px-6 py-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-accent">{t("horizon.kicker")}</div>
          <h1 className="text-[18px] font-semibold leading-tight text-ink">{t("horizon.title")}</h1>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Segmented
            value={mode}
            onChange={setMode}
            options={[
              { value: "globe", label: t("horizon.globe") },
              { value: "flat", label: t("horizon.flat") },
            ]}
          />
          <Segmented
            value={reading}
            onChange={setReading}
            options={[
              { value: "situation", label: t("horizon.situation") },
              { value: "forecast", label: t("horizon.forecastView") },
            ]}
          />
          <Segmented
            value={layer}
            onChange={(v) => {
              setLayer(v);
              setSelected(null);
            }}
            options={[
              { value: "all", label: t("horizon.layerAll") },
              { value: "blocs", label: t("horizon.layerBlocs") },
              { value: "economy", label: t("horizon.layerEconomy") },
              { value: "signals", label: t("horizon.layerSignals") },
            ]}
          />
          <button
            type="button"
            disabled={refreshing || loading}
            onClick={() => loadHorizon(undefined, true)}
            title={t("horizon.refresh")}
            className="inline-flex items-center gap-1.5 rounded-sm border border-hair bg-paper px-2.5 py-1 text-[11.5px] text-muted transition-colors hover:border-faint hover:text-ink disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? "animate-spin text-accent" : ""} />
            {refreshing ? t("horizon.refreshing") : t("horizon.refresh")}
          </button>
        </div>
      </div>

      {/* Corps principal : Carte interactive (gauche) + Dossiers de Cabinet (droite) */}
      <div className="grid min-h-0 flex-1 lg:grid-cols-[1fr_470px]">
        <div className="flex min-h-0 flex-col overflow-y-auto px-5 pb-3 pt-3">
          {headline && (
            <div className="mb-3 rounded-sm border-l-2 border-accent bg-surface/70 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink">
              {headline}
            </div>
          )}

          {loading && !data ? (
            <Loading />
          ) : error ? (
            <Empty>{error}</Empty>
          ) : (
            <HorizonMap
              countries={data?.countries || []}
              arcs={data?.arcs || []}
              chokepoints={(data?.chokepoints || []).map((p) => ({
                id: p.id,
                choke_id: p.choke_id,
                name: typeof p.name === "string" ? p.name : prose(p.name, locale),
                lat: p.lat,
                lon: p.lon,
                delay: p.delay ? prose(p.delay, locale) : undefined,
              }))}
              pulses={pulses}
              blocs={blocsForMap}
              layer={layer}
              reading={lookingAhead ? "forecast" : reading}
              mode={mode}
              selected={activeDossier?.id || selected}
              onSelect={setSelected}
            />
          )}

          {/* Frise Passé (replay corpus) ↔ Futur (projection active) */}
          {bounds && futureMax != null && cursor != null && (
            <label className="mt-auto flex items-center gap-3 pt-3 text-[11px] text-muted">
              <span className="num w-20 shrink-0">{data?.min}</span>
              <input
                type="range"
                className="w-full accent-[var(--color-accent)]"
                min={bounds.min}
                max={futureMax}
                value={Math.min(futureMax, Math.max(bounds.min, cursor))}
                aria-label={t("horizon.time")}
                onChange={(e) => {
                  const next = +e.target.value;
                  setCursor(next);
                  setReading(next > bounds.max ? "forecast" : "situation");
                }}
              />
              <span className="num w-28 shrink-0 text-right font-medium text-ink">
                {lookingAhead || reading === "forecast" ? t("horizon.ahead") : data?.as_of}
              </span>
            </label>
          )}
        </div>

        {/* Colonne de droite : Liste des Dossiers ou Note de Cabinet en 5 blocs */}
        <aside className="min-h-0 overflow-y-auto border-t border-hair bg-paper lg:border-l lg:border-t-0">
          {!activeDossier && (
            <div>
              <div className="flex items-center justify-between border-b border-hair-soft px-4 py-2.5 text-[11px] font-medium uppercase tracking-[0.12em] text-faint">
                <span>{t("horizon.dossiersCount", { n: shown.length })}</span>
                <span>{data?.as_of}</span>
              </div>
              <ul className="divide-y divide-hair-soft">
                {shown.map((f) => {
                  const barColor = KIND_ACCENT[f.kind] || KIND_ACCENT.signal;
                  const title = prose(f.title, locale);
                  const call = prose(f.line, locale);
                  return (
                    <li key={f.id}>
                      <button
                        type="button"
                        onClick={() => setSelected(f.id)}
                        className="group relative block w-full px-4 py-3.5 text-left transition-colors hover:bg-surface"
                      >
                        <span
                          className="absolute inset-y-0 left-0 w-[3px]"
                          style={{ background: barColor }}
                        />
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="text-[10px] font-bold uppercase tracking-[0.1em]" style={{ color: barColor }}>
                            {t(`horizon.kind.${f.kind}`)}
                          </span>
                          <div className="flex items-center gap-1.5">
                            <Badge tone={f.chance === "likely" ? "accent" : f.chance === "possible" ? "default" : "faint"}>
                              {t(`horizon.chance.${f.chance}`)}
                            </Badge>
                            {f.delay && (
                              <span className="num rounded-sm border border-hair px-1.5 py-[1px] text-[10px] font-semibold text-ink">
                                {prose(f.delay, locale)}
                              </span>
                            )}
                          </div>
                        </div>

                        {title && (
                          <div className="mt-1.5 text-[14px] font-semibold leading-snug text-ink group-hover:text-accent-strong">
                            {title}
                          </div>
                        )}
                        <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{call}</p>

                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
                          {f.countries.map((c) => (
                            <span key={c} className="inline-flex items-center gap-1 rounded-sm bg-surface px-1.5 py-0.5 text-ink">
                              {flag(c)} {countryName(c)}
                            </span>
                          ))}
                        </div>
                      </button>
                    </li>
                  );
                })}
                {!loading && !shown.length && (
                  <li className="px-4 py-8">
                    <Empty>{t("horizon.noForecast")}</Empty>
                  </li>
                )}
              </ul>
            </div>
          )}

          {activeDossier && (() => {
            const barColor = KIND_ACCENT[activeDossier.kind] || KIND_ACCENT.signal;
            const scenarios =
              (locale === "en" ? activeDossier.scenarios?.en : activeDossier.scenarios?.fr) || [];
            const signposts =
              locale === "en" ? activeDossier.signposts?.en : activeDossier.signposts?.fr;
            return (
              <div className="px-5 py-4">
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    className="text-[11.5px] text-muted hover:text-ink"
                    onClick={() => setSelected(null)}
                  >
                    {t("horizon.back")}
                  </button>
                  <button
                    type="button"
                    onClick={() => openInAssistant(activeDossier)}
                    className="inline-flex items-center gap-1 rounded-sm border border-accent/50 bg-tint px-2.5 py-1 text-[11px] font-semibold text-accent-strong hover:bg-accent hover:text-paper"
                  >
                    <Sparkles size={11} /> {t("horizon.askAssistant")}
                  </button>
                </div>

                {/* En-tête du dossier */}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-[10.5px] font-bold uppercase tracking-[0.12em]" style={{ color: barColor }}>
                    {t(`horizon.kind.${activeDossier.kind}`)}
                  </span>
                  <Badge tone={activeDossier.chance === "likely" ? "accent" : activeDossier.chance === "possible" ? "default" : "faint"}>
                    {t(`horizon.chance.${activeDossier.chance}`)}
                  </Badge>
                  {activeDossier.delay && (
                    <span className="num rounded-sm border border-hair px-1.5 py-[1px] text-[10.5px] font-semibold text-ink">
                      {prose(activeDossier.delay, locale)}
                    </span>
                  )}
                </div>

                <h2 className="mt-2 text-[17px] font-semibold leading-snug text-ink">
                  {prose(activeDossier.title, locale)}
                </h2>

                <div className="mt-2 flex flex-wrap gap-1.5">
                  {activeDossier.countries.map((c) => (
                    <span key={c} className="inline-flex items-center gap-1 rounded-sm border border-hair-soft bg-surface px-2 py-0.5 text-[11.5px] text-ink">
                      {flag(c)} {countryName(c)}
                    </span>
                  ))}
                </div>

                {/* BLOC 1 — Prévision opérationnelle */}
                <section className="mt-4 rounded-sm border-l-[3px] bg-surface p-3.5" style={{ borderColor: barColor }}>
                  <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">
                    01 · {t("horizon.block.forecast")}
                  </div>
                  <p className="mt-1 text-[14px] font-medium leading-relaxed text-ink">
                    {prose(activeDossier.blocks?.forecast, locale)}
                  </p>
                </section>

                {/* BLOC 2 — Lecture stratégique & pourquoi maintenant */}
                <section className="mt-4">
                  <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">
                    02 · {t("horizon.block.dynamic")}
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink">
                    {prose(activeDossier.blocks?.dynamic, locale)}
                  </p>
                  {activeDossier.ruptures && activeDossier.ruptures.length > 0 && (
                    <div className="mt-2.5 space-y-1 rounded-sm border border-hair-soft bg-surface/60 px-3 py-2 text-[11.5px]">
                      <div className="flex items-center gap-1.5 font-semibold text-ink">
                        <ShieldAlert size={12} className="text-accent" />
                        {t("horizon.block.ruptures")}
                      </div>
                      {activeDossier.ruptures.map((r, idx) => (
                        <div key={idx} className="text-muted">
                          <b className="text-ink">{flag(r.country)} {r.outlet}</b> {t("horizon.ruptureNote")}.
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {/* BLOC 3 — Les 3 trajectoires concrètes */}
                {scenarios.length > 0 && (
                  <section className="mt-4">
                    <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">
                      03 · {t("horizon.block.outcomes")}
                    </div>
                    <div className="mt-2 space-y-2">
                      {scenarios.map((sc, idx) => (
                        <div
                          key={idx}
                          className={`rounded-sm border p-2.5 text-[12.5px] ${
                            idx === 0 ? "border-accent/40 bg-tint/50" : "border-hair-soft bg-paper"
                          }`}
                        >
                          <div className="font-semibold text-ink">{sc.name}</div>
                          <div className="mt-0.5 leading-relaxed text-muted">{sc.desc}</div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {/* BLOC 4 — Signposts (Ce qui confirme / Ce qui désamorce) */}
                {signposts && (signposts.confirm || signposts.abort) && (
                  <section className="mt-4">
                    <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">
                      04 · {t("horizon.block.signs")}
                    </div>
                    <div className="mt-2 space-y-2 text-[12.5px]">
                      {signposts.confirm && (
                        <div className="flex items-start gap-2 rounded-sm border border-hair-soft bg-surface/50 p-2.5">
                          <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-accent-strong" />
                          <div>
                            <span className="font-semibold text-ink">{t("horizon.confirmLabel")} : </span>
                            <span className="text-muted">{signposts.confirm}</span>
                          </div>
                        </div>
                      )}
                      {signposts.abort && (
                        <div className="flex items-start gap-2 rounded-sm border border-hair-soft bg-surface/50 p-2.5">
                          <XCircle size={14} className="mt-0.5 shrink-0 text-faint" />
                          <div>
                            <span className="font-semibold text-ink">{t("horizon.abortLabel")} : </span>
                            <span className="text-muted">{signposts.abort}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                )}

                {/* BLOC 5 — Enjeu souverain, énergétique & économique */}
                <section className="mt-4">
                  <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-accent">
                    05 · {t("horizon.block.stake")}
                  </div>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-ink">
                    {prose(activeDossier.blocks?.stake, locale)}
                  </p>
                </section>

                {/* Preuves primaires transfrontalières */}
                {activeDossier.evidence.length > 0 && (
                  <section className="mt-5 border-t border-hair pt-3.5">
                    <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-faint">
                      {t("horizon.block.sources")}
                    </div>
                    <ul className="mt-2 space-y-2">
                      {activeDossier.evidence.map((e) => (
                        <li key={e.id} className="text-[12px]">
                          <Link
                            to={`/articles/${e.id}`}
                            className="inline-flex items-start gap-1 font-medium text-ink hover:text-accent-strong"
                          >
                            <span>{e.title || t("common.untitled")}</span>
                            <ArrowUpRight size={12} className="mt-0.5 shrink-0 opacity-60" />
                          </Link>
                          <div className="text-[11px] text-faint">
                            {e.country ? `${flag(e.country)} ` : ""}{e.outlet} · {e.date}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            );
          })()}
        </aside>
      </div>
    </div>
  );
}
