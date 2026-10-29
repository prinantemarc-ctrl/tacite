import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getJournalist, getJournalistArticles } from "../api";
import { Card, Badge, Stat, Table, Loading, ErrorState, PageHeader, Score, Empty, Callout, Term } from "../components";
import { splitBio, journalistBeat } from "./JournalistsPage";
import ContactsCard from "../components/ContactsCard";
import { useI18n } from "../i18n/I18nProvider";
import { angleLabel, beatLabel, sourceTypeLabel, toneWordLabel } from "../i18n/mapped";

export default function JournalistDetailPage() {
  const { t, intl, locale } = useI18n();
  const { id } = useParams<{ id: string }>();
  const [journalist, setJournalist] = useState<any>(null);
  const [articles, setArticles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    Promise.all([getJournalist(+id), getJournalistArticles(+id)])
      .then(([j, a]) => { setJournalist(j); setArticles(a); })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Loading />;
  if (!journalist) return <ErrorState>{t("journalists.notFound")}</ErrorState>;

  const prof = journalist.latest_profile;
  const beat = journalistBeat(journalist);
  const bio = splitBio(journalist.bio).text;

  return (
    <div>
      <PageHeader
        kicker={beat ? `${t("journalists.kicker")} · ${beatLabel(beat, t)}` : t("journalists.kicker")}
        title={journalist.name}
        subtitle={
          <>
            <Link to={`/outlets/${journalist.outlet_id}`} className="text-ink underline decoration-hair hover:text-accent-strong">{journalist.outlet_name || t("journalists.outletFallback", { id: journalist.outlet_id })}</Link>
            {" · "}{journalist.role}
          </>
        }
        actions={<div className="text-right"><Score value={journalist.accessibility_score || 0} label={t("journalists.accessibility")} /><div className="mt-1 text-[10.5px]"><Term k="accessibility">{t("journalists.whatIsAccessibility")}</Term></div></div>}
      />

      {bio && <p className="mb-6 max-w-3xl text-[14px] leading-[1.55] text-muted">{bio}</p>}

      <div className="mb-5"><ContactsCard journalistId={journalist.id} initial={journalist.contacts || []} scannedAt={journalist.contacts_scanned_at} /></div>

      {prof ? (
        <div className="mb-6 grid grid-cols-2 gap-6 md:grid-cols-4">
          <Stat label={t("journalists.productivity")} value={prof.productivity || 0} sub={t("journalists.perWeek")} help="productivity" />
          <Stat label={t("journalists.tone")} value={<span className="text-[18px]">{prof.tone ? toneWordLabel(prof.tone, t) : t("common.dash")}</span>} help="tone" />
          <Stat label={t("journalists.biases")} value={prof.biases?.length || 0} help="biases" />
          <Stat label={t("journalists.vulnerabilities")} value={prof.vulnerabilities?.length || 0} tone={prof.vulnerabilities?.length ? "alert" : "ink"} help="vulnerabilities" />
        </div>
      ) : (
        <div className="mb-6"><Callout label={t("journalists.profile")}>{t("journalists.noProfile")}</Callout></div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title={t("journalists.fixations")} aside={t("journalists.fixationsAside")} help="themes">
          {prof?.themes?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {prof.themes.map((theme: any, i: number) => (
                <Badge key={i} tone={i < 3 ? "accent" : "default"}>{theme.label} <span className="ml-1 num opacity-70">×{theme.count}</span></Badge>
              ))}
            </div>
          ) : <Empty>{t("journalists.noData")}</Empty>}
        </Card>

        <Card title={t("journalists.preferredSources")} help="sources">
          {prof?.preferred_sources?.length ? (
            <div className="flex flex-wrap gap-1.5">
              {prof.preferred_sources.map((s: any, i: number) => <Badge key={i}>{sourceTypeLabel(s.type, t)} <span className="ml-1 num opacity-70">×{s.count}</span></Badge>)}
            </div>
          ) : <Empty>{t("journalists.noData")}</Empty>}
        </Card>

        {prof?.biases?.length > 0 && (
          <Card title={t("journalists.biases")} help="biases">
            <ul className="list-disc space-y-1 pl-4 text-[12.5px] text-muted marker:text-accent">
              {prof.biases.map((b: string, i: number) => <li key={i}>{b}</li>)}
            </ul>
          </Card>
        )}

        {prof?.vulnerabilities?.length > 0 && (
          <Card title={t("journalists.vulnerabilitiesFound")} help="vulnerabilities">
            <ul className="divide-y divide-hair-soft">
              {prof.vulnerabilities.map((v: any, i: number) => (
                <li key={i} className="flex items-start gap-3 py-2">
                  <Badge tone="alert">{v.label}</Badge>
                  <span className="text-[12.5px] text-muted">{v.explanation}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <Card title={t("journalists.recentArticles")} aside={t("journalists.signedN", { n: articles.length })} className="mt-5">
        {articles.length ? (
          <Table headers={[t("journalists.colTitle"), t("journalists.colDate"), <Term k="tone">{t("journalists.colTone")}</Term>, <Term k="angle">{t("journalists.colAngle")}</Term>]} dense>
            {articles.slice(0, 15).map((a) => (
              <tr key={a.id}>
                <td className="max-w-xl"><a href={a.url} target="_blank" rel="noopener" className="text-ink hover:text-accent-strong">{a.title}</a></td>
                <td className="num whitespace-nowrap text-faint">{new Date(a.published_at).toLocaleDateString(intl)}</td>
                <td>{a.extracted_data?.tone ? <Badge>{toneWordLabel(a.extracted_data.tone, t)}</Badge> : <span className="text-faint">{t("common.dash")}</span>}</td>
                <td>{a.extracted_data?.angle ? <Badge tone="faint">{angleLabel(a.extracted_data.angle, t)}</Badge> : <span className="text-faint">{t("common.dash")}</span>}</td>
              </tr>
            ))}
          </Table>
        ) : <Empty>{t("journalists.noArticles")}</Empty>}
      </Card>

      <div className="closing-rule mt-12" />
    </div>
  );
}
