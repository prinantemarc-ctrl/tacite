import {
  Radar, RadarChart as RechartsRadar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Legend,
} from "recharts";
import { T, CHART_FONT } from "../theme";
import { useI18n } from "../i18n/I18nProvider";

const AXIS_KEYS = [
  "economy", "society", "immigration", "europe", "ecology", "security",
  "secularism", "international", "institutions", "media", "justice", "technology",
];

interface Props {
  official?: Record<string, number>;
  real?: Record<string, number>;
  axes?: string[];
}

/** Ligne déclarée (encre, pointillé) vs ligne mesurée (bronze, plein). */
export default function DoubleRadar({ official = {}, real = {}, axes }: Props) {
  const { t, intl, locale } = useI18n();
  const axisKeys = axes || AXIS_KEYS;
  const data = axisKeys.map((key) => {
    const label = t(`axis.${key}`);
    return {
      axis: label !== `axis.${key}` ? label : key,
      official: (official[key] ?? 0) * 50 + 50, // -1..1 → 0..100
      real: (real[key] ?? 0) * 50 + 50,
    };
  });

  return (
    <ResponsiveContainer width="100%" height={380}>
      <RechartsRadar data={data} cx="50%" cy="50%" outerRadius="72%">
        <PolarGrid stroke={T.hair} />
        <PolarAngleAxis dataKey="axis" tick={{ fill: T.muted, fontSize: 10.5, fontFamily: CHART_FONT }} />
        <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
        <Radar name={t("series.declared")} dataKey="official" stroke={T.ink} fill={T.ink} fillOpacity={0.04} strokeWidth={1.25} strokeDasharray="5 3" />
        <Radar name={t("series.measured")} dataKey="real" stroke={T.accent} fill={T.accent} fillOpacity={0.18} strokeWidth={1.5} />
        <Legend
          iconType="plainline"
          wrapperStyle={{ fontSize: 10.5, fontFamily: CHART_FONT, color: T.muted, letterSpacing: "0.08em", textTransform: "uppercase" }}
        />
      </RechartsRadar>
    </ResponsiveContainer>
  );
}
