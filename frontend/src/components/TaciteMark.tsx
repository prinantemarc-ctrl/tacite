const PATH =
  "M32 5.8C36.8 5.6 44 8.8 50.2 11.6C54.6 13.8 58.4 16 57.2 18.4C55.6 21.4 50.8 23.6 46.4 24.6C45.2 26.4 44.4 28.8 44.2 32C44.4 35.2 45.2 37.6 46.4 39.4C50.8 40.4 55.6 42.6 57.2 45.6C58.4 48 54.6 50.2 50.2 52.4C44 55.2 36.8 58.4 32 58.2C27.2 58.4 20 55.2 13.8 52.4C9.4 50.2 5.6 48 6.8 45.6C8.4 42.6 13.2 40.4 17.6 39.4C18.8 37.6 19.6 35.2 19.8 32C19.6 28.8 18.8 26.4 17.6 24.6C13.2 23.6 8.4 21.4 6.8 18.4C5.6 16 9.4 13.8 13.8 11.6C20 8.8 27.2 5.6 32 5.8ZM23.6 18.4C26.2 15.8 28.8 15.8 32 15.8C35.2 15.8 37.8 15.8 40.4 18.4C37.8 21 35.2 21 32 21C28.8 21 26.2 21 23.6 18.4ZM23.6 45.6C26.2 43 28.8 43 32 43C35.2 43 37.8 43 40.4 45.6C37.8 48.2 35.2 48.2 32 48.2C28.8 48.2 26.2 48.2 23.6 45.6Z";

type Props = {
  size?: number;
  className?: string;
  /** Carré noir + glyphe blanc, comme l’icône d’app. */
  framed?: boolean;
};

/** Monogramme Tacite : parchemin très stylisé. */
export function TaciteMark({ size = 24, className = "", framed = false }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      className={className}
      aria-hidden
    >
      {framed && <rect width="64" height="64" rx="14.3" fill="#0a0a0a" />}
      <path fill={framed ? "#fff" : "currentColor"} fillRule="evenodd" d={PATH} />
    </svg>
  );
}
