/** Pont vers la coque Electron. Dans le navigateur, tout est un no-op. */

export type NativePicked = {
  name: string;
  path: string;
  type: string;
  base64: string;
};

export type DesktopBridge = {
  isDesktop: true;
  platform?: string;
  onStatus?: (cb: (payload: { message?: string; error?: boolean }) => void) => () => void;
  onMenu?: (cb: (payload: { action: string }) => void) => () => void;
  retry?: () => Promise<void>;
  connectCursor?: (opts?: { token?: string; url?: string; showDialog?: boolean }) => Promise<{ ok: boolean; error?: string }>;
  getInfo?: () => Promise<{ isDesktop: boolean; platform: string; version: string; origin: string }>;
  openFiles?: (opts?: { filters?: { name: string; extensions: string[] }[]; multiple?: boolean }) => Promise<NativePicked[]>;
  showNotification?: (title: string, body?: string) => Promise<{ ok: boolean }>;
  setBadge?: (count: number | string | null) => Promise<{ ok: boolean }>;
};

export const MAC_APP_URL = "https://github.com/prinantemarc-ctrl/tacite/releases/latest/download/Tacite-mac.dmg";

const DOC_FILTERS = [{ name: "Documents", extensions: ["pdf", "html", "htm", "txt", "md", "csv", "docx", "xlsx", "json"] }];
const CSV_FILTERS = [{ name: "CSV", extensions: ["csv"] }];

let pendingOutletCsv: File | null = null;
let pendingAttachments: { name: string; text: string; chars: number }[] = [];

export function bridge(): DesktopBridge | null {
  const w = window as Window & { tacite?: DesktopBridge };
  return w.tacite?.isDesktop ? w.tacite : null;
}

export function isDesktop(): boolean {
  return bridge() != null;
}

export function nativeToFile(picked: NativePicked): File {
  const bin = atob(picked.base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new File([bytes], picked.name, { type: picked.type || "application/octet-stream" });
}

export async function pickNativeFiles(kind: "documents" | "outlets"): Promise<File[]> {
  const b = bridge();
  if (!b?.openFiles) return [];
  const rows = await b.openFiles({
    multiple: kind === "documents",
    filters: kind === "outlets" ? CSV_FILTERS : DOC_FILTERS,
  });
  return (rows || []).map(nativeToFile);
}

export function stashOutletCsv(file: File) {
  pendingOutletCsv = file;
}

export function takePendingOutletCsv(): File | null {
  const file = pendingOutletCsv;
  pendingOutletCsv = null;
  return file;
}

export function stashAttachments(items: { name: string; text: string; chars: number }[]) {
  pendingAttachments = items;
}

export function takePendingAttachments(): { name: string; text: string; chars: number }[] {
  const items = pendingAttachments;
  pendingAttachments = [];
  return items;
}
