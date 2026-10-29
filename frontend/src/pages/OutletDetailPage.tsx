import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, LineChart, Line, Legend } from "recharts";
import { getOutlet, getOutletProfiles, getDoubleClassification, getOutletArticles, kitForCountry } from "../api";
import { Card, GapBar, Table, Loading, ErrorState, PageHeader, Score, Empty, ScorePill, Badge, Callout, Term } from "../components";
import DoubleRadar from "../components/RadarChart";
import { T, axisTick, tooltipStyle, SERIES, CHART_FONT } from "../theme";
import { flag, countryName, languageName, axisLabel } from "../geo";
import { useI18n } from "../i18n/I18nProvider";
import { orientationLabel, toneWordLabel } from "../i18n/mapped";

const AXES = [
  "economy", "society", "immigration", "europe", "ecology", "security",
  "secularism", "international", "institutions", "media", "justice", "technology",
] as const;

export default function OutletDetailPage() {
  const { t, intl } = useI18n();
  const { id } = useParams<{ id: string }>();
  const [outlet, setOutlet] = useState<any>(null);
  const [profiles, setProfiles] = useState<any[]>([]);
  const [double, setDouble] = useState<any>(null);
  const [articles, setArticles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [axes, setAxes] = useState<string[]>([...AXES]);

  useEffect(() => {
    if (!id) return;
    Promise.all([getOutlet(+id), getOutletProfiles(+id), getDoubleClassification(+id), getOutletArticles(+id)])
      .then(([o, p, d, a]) => { setOutlet(o); setProfiles(p); setDouble(d); setArticles(a); })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (!outlet?.country) return;
    kitForCountry(outlet.country).then((r) => {
      const ids = r.display_axes || (r.kit?.axes || []).map((a: any) => a.id);
      if (ids?.length) setAxes(ids);
    }).catch(() => undefined);
  }, [outlet?.country]);

  if (loading) return <Loading />;
  if (!outlet) return <ErrorState>{t("outlets.notFound")}</ErrorState>;

  const weightName = (k: string) => {
    const w = t(`weight.${k}`);
    return w === `weight.${k}` ? k : w;
  };
  const statusLabel = (s?: string) => {
    if (!s) return t("common.dash");
    const mapped = t(`status.${s}`);
    return mapped !== `status.${s}` ? mapped : s;
  };

  const prof = outlet.latest_profile;
  const official = double?.official || outlet.official_classification || {};
  const real = double?.real || prof?.real_classification || {};
  const gaps = double?.gap || prof?.gap_from_official || {};
  const captured = outlet.articles_total ?? articles.length;
  const articleCount = prof?.article_count || captured;
  const confidence = articleCount >= 30 ? t("confidence.high") : articleCount >= 10 ? t("confidence.medium") : t("confidence.low");
  const plural = articleCount > 1 ? "s" : "";
  const capturedPlural = captured > 1 ? "s" : "";

  const compData = prof?.component_scores
    ? Object.entries(prof.component_scores).map(([k, v]) => ({ name: weightName(k), value: Math.round((v as number) * 100) }))
    : [];

  const histData = [...profiles].reverse().map((p) => {
    const entry: any = { semaine: p.week };
    for (const [axis, val] of Object.entries(p.real_classification || {})) entry[axisLabel(axis)] = +((val as number) * 50 + 50).toFixed(1);
    return entry;
  });
  const topAxes = Object.entries(gaps).sort(([, a], [, b]) => Math.abs(b as number) - Math.abs(a as number)).slice(0, 4).map(([k]) => axisLabel(k));

  return (
    <div>
      <PageHeader
        kicker={`${t("outlets.kicker")} · ${flag(outlet.country)} ${countryName(outlet.country)} · ${languageName(outlet.language)}`}
        title={outlet.name}
        subtitle={<>
          {outlet.declared_orientation ? orientationLabel(outlet.declared_orientation, t) : t("outlets.noOrientation")}
          {outlet.website_url && <> · <a href={outlet.website_url} target="_blank" rel="noopener" className="underline decoration-hair hover:text-accent-strong">{outlet.website_url.replace(/^https?:\/\//, "")}</a></>}
          {" · "}
          {outlet.collect_enabled === 0
            ? <Badge tone="faint">{t("outlets.collectPaused")}</Badge>
            : (outlet.feeds?.length || 0) > 0
              ? <Term k="collect_modes">{t("outlets.collectRss", { n: outlet.feeds.length })}</Term>
              : <Term k="collect_modes">{t("outlets.collectIndirect")}</Term>}
        </>}
        actions={<div className="text-right"><Score value={outlet.influence_score || 0} label={outlet.influence_rank ? t("outlets.influenceRank", { n: outlet.influence_rank }) : t("outlets.influence")} /><div className="mt-1 text-[10.5px]"><Term k="influence">{t("outlets.whatInfluence")}</Term></div></div>}
      />

      {prof && articleCount < 30 && (
        <div className="mb-5">
          <Callout label={t("outlets.methodReserve")} warn>
            <Term k="measured">{t("outlets.measuredLine")}</Term> {t("outlets.thinSample", { n: articleCount, s: plural })} <Term k="confidence">{t("outlets.confidenceWord")}</Term> {confidence}. {t("outlets.thinSampleEnd")}
          </Callout>
        </div>
      )}
      {!prof && captured > 0 && (
        <div className="mb-5">
          <Callout label={t("outlets.collect")}>
            {t("outlets.capturedPending", { n: captured, s: capturedPlural })}
          </Callout>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <Card title={t("outlets.radarTitle")} aside={<><Term k="declared">{t("outlets.declaredAdj")}</Term> {t("outlets.radarAsideDot")} <Term k="measured">{t("outlets.measuredAdj")}</Term> {t("outlets.radarAsideBronze")}</>} help={["declared", "measured", "axes"]} className="lg:col-span-3">
          <DoubleRadar official={official} real={real} axes={axes} />
        </Card>
        <Card title={t("outlets.compTitle")} help={["influence", "comp_citation", "comp_agenda"]} className="lg:col-span-2">
          {compData.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={compData} layout="vertical" margin={{ left: 0, right: 24 }}>
                <CartesianGrid horizontal={false} stroke={T.hairSoft} />
                <XAxis type="number" domain={[0, 100]} tick={axisTick} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="name" tick={axisTick} width={80} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: T.tint }} />
                <Bar dataKey="value" fill={T.accent} radius={[0, 2, 2, 0]} barSize={12} label={{ position: "right", fill: T.muted, fontSize: 10.5, fontFamily: CHART_FONT }} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty>{t("outlets.compEmpty")}</Empty>
          )}
        </Card>
      </div>

      <Card title={t("outlets.gapsTitle")} aside={t("outlets.gapsAside")} help={["gap", "confidence"]} className="mt-5">
        <Table headers={[t("outlets.colAxis"), <Term k="declared">{t("series.declared")}</Term>, <Term k="measured">{t("series.measured")}</Term>, <Term k="gap">{t("outlets.colGapShort")}</Term>]} dense>
          {[...axes].sort((a, b) => Math.abs((gaps[b] ?? 0) as number) - Math.abs((gaps[a] ?? 0) as number)).map((key) => {
            const label = axisLabel(key);
            const off = (official[key] ?? 0) as number;
            const re = (real[key] ?? 0) as number;
            const gap = (gaps[key] ?? re - off) as number;
            const n = (prof?.axis_n || {})[key];
            const thin = n !== undefined && n < 10;
            return (
              <tr key={key} className={thin ? "opacity-40" : ""}>
                <td className="font-medium text-ink">{label}{thin ? <span className="ml-1 text-[10px] font-normal text-faint">{t("common.dash")}</span> : ""}</td>
                <td className="num text-muted">{off > 0 ? "+" : ""}{off.toFixed(2)}</td>
                <td className="num text-accent-strong">{re > 0 ? "+" : ""}{re.toFixed(2)}</td>
                <td className="min-w-[200px]"><GapBar value={gap} /></td>
              </tr>
            );
          })}
        </Table>
      </Card>

      {histData.length > 1 && (
        <Card title={t("outlets.trajTitle")} aside={t("outlets.trajAside")} help={["measured", "drift"]} className="mt-5">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={histData} margin={{ left: -10, right: 12 }}>
              <CartesianGrid stroke={T.hairSoft} vertical={false} />
              <XAxis dataKey="semaine" tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false} />
              <YAxis domain={[0, 100]} tick={axisTick} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 10.5, fontFamily: CHART_FONT, color: T.muted }} />
              {topAxes.map((label, i) => (
                <Line key={label} type="monotone" dataKey={label} stroke={SERIES[i]} dot={false} strokeWidth={i === 1 ? 1.75 : 1.25} strokeDasharray={i === 2 ? "4 3" : undefined} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {prof?.drift_alerts?.length > 0 && (
        <Card title={t("outlets.driftsTitle")} help="drift" className="mt-5">
          <div className="flex flex-wrap gap-1.5">
            {prof.drift_alerts.map((d: any, i: number) => (
              <Badge key={i} tone={Math.abs(d.change) > 0.5 ? "alert" : "accent"}>{axisLabel(d.axis)} {d.change > 0 ? "+" : ""}{d.change.toFixed(2)}</Badge>
            ))}
          </div>
        </Card>
      )}

      {outlet.topics?.length > 0 && (
        <Card title={t("outlets.topicsTitle")} aside={t("common.week8")} help="outlet_topics" className="mt-5">
          <div className="flex flex-wrap gap-1.5">
            {outlet.topics.map((topic: { label: string; count: number }, i: number) => (
              <Badge key={topic.label} tone={i < 3 ? "accent" : "default"}>{topic.label} <span className="ml-1 num opacity-70">×{topic.count}</span></Badge>
            ))}
          </div>
        </Card>
      )}

      <Card title={t("pages.journalists")} aside={<>{t("outlets.journAside", { n: outlet.journalists_count || outlet.journalists?.length || 0 })} <Term k="accessibility">{t("outlets.accessibility")}</Term> · <Link to={`/journalists?outlet_id=${outlet.id}`} className="hover:text-ink">{t("outlets.journFilter")}</Link></>} help={["accessibility", "top_journalists"]} className="mt-5">
        {outlet.journalists?.length ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {[...outlet.journalists].sort((a: any, b: any) => (b.articles_window || 0) - (a.articles_window || 0) || (b.accessibility_score || 0) - (a.accessibility_score || 0)).map((j: any) => (
              <Link key={j.id} to={`/journalists/${j.id}`} className="inline-flex items-center gap-1.5 text-[12.5px] text-ink hover:text-accent-strong">
                {j.name}
                {(j.articles_window || 0) > 0 && <span className="num text-faint">×{j.articles_window}</span>}
                <ScorePill value={j.accessibility_score} />
              </Link>
            ))}
          </div>
        ) : (
          <Empty>{t("outlets.journEmpty")}</Empty>
        )}
      </Card>

      <Card title={t("outlets.artsTitle")} aside={<Link to={`/articles?outlet_id=${outlet.id}`} className="hover:text-ink">{t("outlets.artsTotal", { n: captured })}</Link>} className="mt-5">
        {articles.length ? (
          <Table headers={[t("outlets.colTitle"), t("outlets.colDate"), t("outlets.colStatus"), <Term k="tone">{t("outlets.colTone")}</Term>]} dense>
            {articles.slice(0, 20).map((a) => (
              <tr key={a.id}>
                <td className="max-w-xl">
                  <Link to={`/articles/${a.id}`} className="text-ink hover:text-accent-strong">{a.title}</Link>
                </td>
                <td className="num whitespace-nowrap text-faint">{a.published_at ? new Date(a.published_at).toLocaleDateString(intl) : t("common.dash")}</td>
                <td className="text-faint">{statusLabel(a.analysis_status)}</td>
                <td>{a.extracted_data?.tone ? <Badge>{toneWordLabel(a.extracted_data.tone, t)}</Badge> : <span className="text-faint">{t("common.dash")}</span>}</td>
              </tr>
            ))}
          </Table>
        ) : <Empty>{t("outlets.artsEmpty")}</Empty>}
      </Card>

      <div className="closing-rule mt-12" />
    </div>
  );
}
