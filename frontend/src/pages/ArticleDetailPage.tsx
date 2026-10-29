import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticle } from "../api";
import { Card, Badge, Loading, ErrorState, PageHeader, Empty, GapBar } from "../components";
import { flag } from "../geo";
import { useI18n } from "../i18n/I18nProvider";
import { angleLabel, sourceTypeLabel, toneWordLabel } from "../i18n/mapped";

const STATUS_TONE: Record<string, "default" | "accent" | "faint" | "alert"> = {
  analyzed: "accent",
  embedded_only: "faint",
  pending: "default",
  failed: "alert",
  error: "alert",
  duplicate: "faint",
};

const AXES = [
  "economy", "society", "immigration", "europe",
  "ecology", "security", "secularism", "international",
  "institutions", "media", "justice", "technology",
] as const;

function statusKey(s: string) {
  return s === "failed" ? "error" : s;
}

export default function ArticleDetailPage() {
  const { t, intl } = useI18n();
  const { id } = useParams<{ id: string }>();
  const [article, setArticle] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    getArticle(+id).then(setArticle).catch(() => setArticle(null)).finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Loading />;
  if (!article) return <ErrorState>{t("articles.notFound")}</ErrorState>;

  const d = article.extracted_data || {};
  const rawStatus = article.analysis_status || "pending";
  const stKey = statusKey(rawStatus);
  const stLabel = t(`status.${stKey}`);
  const framing = d.framing || {};
  const authors = article.authors?.length
    ? article.authors
    : article.journalist_id
      ? [{ id: article.journalist_id, name: article.journalist_name }]
      : [];

  return (
    <div>
      <PageHeader
        kicker={t("articles.kicker")}
        title={article.title || t("common.untitled")}
        subtitle={
          <>
            <Link to={`/outlets/${article.outlet_id}`} className="text-ink underline decoration-hair hover:text-accent-strong">
              {flag(article.outlet_country)} {article.outlet_name || t("articles.outletFallback", { id: article.outlet_id })}
            </Link>
            {article.published_at && <> · <span className="num">{new Date(article.published_at).toLocaleDateString(intl, { day: "numeric", month: "long", year: "numeric" })}</span></>}
            {article.language && <> · <span className="uppercase">{article.language}</span></>}
          </>
        }
        actions={<Badge tone={STATUS_TONE[rawStatus] || STATUS_TONE.pending}>{stLabel === `status.${stKey}` ? t("status.pending") : stLabel}</Badge>}
      />

      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
        {authors.length > 0 && (
          <span>
            {authors.map((j: any, i: number) => (
              <span key={j.id || i}>
                {i > 0 && ", "}
                {j.id ? <Link to={`/journalists/${j.id}`} className="hover:text-accent-strong">{j.name}</Link> : j.name}
              </span>
            ))}
          </span>
        )}
        {article.url && <a href={article.url} target="_blank" rel="noopener" className="text-accent-strong hover:underline">{t("articles.source")}</a>}
      </div>

      <div className="mb-5 flex flex-wrap gap-1.5">
        {d.topics?.map((topic: any, i: number) => <Badge key={i} tone="accent">{topic.label || topic}</Badge>)}
        {d.tone && <Badge>{toneWordLabel(d.tone, t)}</Badge>}
        {d.angle && <Badge tone="faint">{angleLabel(d.angle, t)}</Badge>}
        {d.sources?.slice(0, 6).map((s: any, i: number) => <Badge key={`s${i}`} tone="faint">{sourceTypeLabel(s.type || s, t)}</Badge>)}
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <Card title={t("articles.framing")} help="framing" className="lg:col-span-2">
          {Object.keys(framing).length ? (
            <div className="space-y-2">
              {(Object.keys(framing).length ? Object.keys(framing) : AXES).map((k) => {
                const v = Number(framing[k] || 0);
                return (
                  <div key={k} className="grid grid-cols-[110px_1fr_48px] items-center gap-2 text-[12px]">
                    <span className="text-muted">{t(`axis.${k}`)}</span>
                    <GapBar value={v} />
                    <span className="num text-right text-faint">{v > 0 ? "+" : ""}{v.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          ) : <Empty>{t("articles.noFraming")}</Empty>}
        </Card>
        <Card title={t("articles.text")} className="lg:col-span-3">
          {article.text ? (
            <p className="whitespace-pre-wrap text-[13.5px] leading-[1.65] text-ink">{article.text}</p>
          ) : <Empty>{t("articles.noText")}</Empty>}
        </Card>
      </div>
    </div>
  );
}
