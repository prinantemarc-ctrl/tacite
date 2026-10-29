import { useId } from "react";
import { TACITE_GLYPH_OPS } from "./taciteGlyph";

type Props = {
  size?: number;
  className?: string;
  /** Carré noir biseauté + glyphe argenté, comme l’icône d’app macOS. */
  framed?: boolean;
};

/** Monogramme Tacite : parchemin déroulé et calames croisés. */
export function TaciteMark({ size = 24, className = "", framed = false }: Props) {
  const uid = useId().replace(/:/g, "");
  const maskId = `tacite-m-${uid}`;
  const inkId = `tacite-i-${uid}`;
  const rimId = `tacite-r-${uid}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      aria-hidden
    >
      <defs>
        {framed && (
          <>
            <linearGradient id={inkId} x1="32" y1="8" x2="32" y2="56" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#ffffff" />
              <stop offset="52%" stopColor="#d7d7d7" />
              <stop offset="100%" stopColor="#acacac" />
            </linearGradient>
            <linearGradient id={rimId} x1="32" y1="0" x2="32" y2="64" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#787879" stopOpacity="0.72" />
              <stop offset="35%" stopColor="#3a3a3c" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#1c1c1e" stopOpacity="0.2" />
            </linearGradient>
          </>
        )}
        <mask id={maskId}>
          <rect width="64" height="64" fill="#000" />
          {TACITE_GLYPH_OPS.map(([fill, d], i) => (
            <path key={i} fill={fill} d={d} />
          ))}
        </mask>
      </defs>
      {framed && (
        <>
          <rect width="64" height="64" rx="14.3" fill="#0a0a0a" />
          <rect x="0.5" y="0.5" width="63" height="63" rx="13.8" stroke={`url(#${rimId})`} strokeWidth="1" />
        </>
      )}
      <rect width="64" height="64" fill={framed ? `url(#${inkId})` : "currentColor"} mask={`url(#${maskId})`} />
    </svg>
  );
}
