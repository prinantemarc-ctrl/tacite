import { app, BrowserWindow, Menu, Notification, dialog, ipcMain, shell, nativeTheme } from "electron";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

let webOrigin = "https://tacite-zs2b.onrender.com";
const CURSOR_MCP_FILE = () => join(homedir(), ".cursor", "mcp.json");
const MAX_FILE = 20 * 1024 * 1024;

const MIME = {
  ".pdf": "application/pdf",
  ".html": "text/html",
  ".htm": "text/html",
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".csv": "text/csv",
  ".json": "application/json",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

function pageUrl() {
  return `${webOrigin}/`;
}
function healthUrl() {
  return new URL("api/health", pageUrl()).href;
}
function mcpUrl() {
  return new URL("api/mcp", pageUrl()).href;
}

let mainWindow = null;
let starting = false;

function appIconPng() {
  const packaged = join(process.resourcesPath, "icon.png");
  const local = join(__dirname, "build/icon.png");
  return existsSync(packaged) ? packaged : local;
}

function sendStatus(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("status", payload);
  }
}

function sendMenu(action) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("menu", { action });
  }
}

async function connectToCursor(opts = { showDialog: true }) {
  try {
    const cursorDir = join(homedir(), ".cursor");
    mkdirSync(cursorDir, { recursive: true });
    const mcpPath = CURSOR_MCP_FILE();
    let cfg = { mcpServers: {} };
    if (existsSync(mcpPath)) {
      try {
        cfg = JSON.parse(readFileSync(mcpPath, "utf8"));
      } catch {
        cfg = { mcpServers: {} };
      }
    }
    if (!cfg.mcpServers || typeof cfg.mcpServers !== "object") {
      cfg.mcpServers = {};
    }
    const entry = { url: (opts?.url && /^https?:\/\//.test(opts.url)) ? opts.url : mcpUrl() };
    if (opts?.token) {
      entry.headers = { Authorization: `Bearer ${opts.token}` };
    }
    cfg.mcpServers.tacite = entry;
    writeFileSync(mcpPath, JSON.stringify(cfg, null, 2) + "\n", "utf8");
    if (opts?.showDialog !== false && mainWindow && !mainWindow.isDestroyed()) {
      await dialog.showMessageBox(mainWindow, {
        type: "info",
        title: "Connecté à Cursor",
        message: "Tacite est maintenant connecté à Cursor (MCP).",
        detail: `Le serveur MCP « tacite » (${entry.url}) a été enregistré dans ~/.cursor/mcp.json.`,
      });
    }
    return { ok: true, path: mcpPath, url: entry.url };
  } catch (e) {
    if (opts?.showDialog !== false && mainWindow && !mainWindow.isDestroyed()) {
      await dialog.showMessageBox(mainWindow, {
        type: "error",
        title: "Erreur de connexion MCP",
        message: "Impossible de mettre à jour ~/.cursor/mcp.json",
        detail: e.message || String(e),
      });
    }
    return { ok: false, error: e.message || String(e) };
  }
}

async function waitFor(url, timeoutMs) {
  const start = Date.now();
  let last = "";
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(4000) });
      if (r.ok) return;
      last = `HTTP ${r.status}`;
    } catch (e) {
      last = e.cause?.code || e.message || "injoignable";
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  throw new Error(`Pas de réponse (${last})`);
}

function loadServerOrigin() {
  const candidates = [
    join(process.resourcesPath || "", "server.json"),
    join(__dirname, "server.json"),
  ];
  for (const path of candidates) {
    try {
      const cfg = JSON.parse(readFileSync(path, "utf8"));
      if (cfg.url) {
        webOrigin = String(cfg.url).replace(/\/$/, "");
        return;
      }
    } catch { /* fichier absent */ }
  }
}

async function boot() {
  if (starting) return;
  starting = true;
  try {
    loadServerOrigin();
    sendStatus({ message: "Connexion à Tacite…" });
    await waitFor(healthUrl(), 25_000);
    if (mainWindow && !mainWindow.isDestroyed()) await mainWindow.loadURL(pageUrl());
  } catch (e) {
    sendStatus({
      error: true,
      idle: true,
      message: e.message || "Tacite est injoignable. Vérifiez la connexion, puis réessayez.",
    });
  } finally {
    starting = false;
  }
}

function showSplash() {
  return mainWindow.loadFile(join(__dirname, "splash.html"));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#1a1916" : "#ffffff",
    title: "Tacite",
    icon: appIconPng(),
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function buildMenu() {
  const isMac = process.platform === "darwin";
  const template = [
    ...(isMac
      ? [{
          label: app.name,
          submenu: [
            { role: "about", label: "À propos de Tacite" },
            { type: "separator" },
            {
              label: "Réglages…",
              accelerator: "CmdOrCtrl+,",
              click: () => sendMenu("settings"),
            },
            {
              label: "Connecter à Cursor (MCP)…",
              click: () => connectToCursor({ showDialog: true }),
            },
            { type: "separator" },
            {
              label: "Relancer Tacite",
              click: async () => {
                await showSplash();
                boot();
              },
            },
            { type: "separator" },
            { role: "hide", label: "Masquer Tacite" },
            { role: "hideOthers", label: "Masquer les autres" },
            { role: "unhide", label: "Tout afficher" },
            { type: "separator" },
            { role: "quit", label: "Quitter Tacite" },
          ],
        }]
      : []),
    {
      label: "Fichier",
      submenu: [
        {
          label: "Importer des documents…",
          accelerator: "CmdOrCtrl+O",
          click: () => sendMenu("import-documents"),
        },
        {
          label: "Importer des médias (CSV)…",
          accelerator: "CmdOrCtrl+Shift+O",
          click: () => sendMenu("import-outlets"),
        },
        { type: "separator" },
        {
          label: "Actualiser",
          accelerator: "CmdOrCtrl+R",
          click: () => sendMenu("refresh"),
        },
      ],
    },
    {
      label: "Édition",
      submenu: [
        { role: "undo", label: "Annuler" },
        { role: "redo", label: "Rétablir" },
        { type: "separator" },
        { role: "cut", label: "Couper" },
        { role: "copy", label: "Copier" },
        { role: "paste", label: "Coller" },
        { role: "selectAll", label: "Tout sélectionner" },
      ],
    },
    {
      label: "Présentation",
      submenu: [
        { role: "reload", label: "Recharger" },
        { role: "togglefullscreen", label: "Plein écran" },
        { type: "separator" },
        { role: "resetZoom", label: "Taille réelle" },
        { role: "zoomIn", label: "Zoom avant" },
        { role: "zoomOut", label: "Zoom arrière" },
      ],
    },
    {
      label: "Fenêtre",
      submenu: [
        { role: "minimize", label: "Réduire" },
        { role: "zoom", label: "Zoom" },
        { type: "separator" },
        {
          label: "Ouvrir dans le navigateur",
          click: () => shell.openExternal(pageUrl()),
        },
        { type: "separator" },
        { role: "front", label: "Tout ramener au premier plan" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

ipcMain.handle("retry", async () => {
  await showSplash();
  boot();
});
ipcMain.handle("connect-cursor", (_e, opts) => connectToCursor(opts || {}));
ipcMain.handle("app-info", () => ({
  isDesktop: true,
  platform: process.platform,
  version: app.getVersion(),
  origin: webOrigin,
}));
ipcMain.handle("open-files", async (_e, opts) => {
  const filters = Array.isArray(opts?.filters) && opts.filters.length
    ? opts.filters
    : [{ name: "Documents", extensions: ["pdf", "html", "htm", "txt", "csv", "md", "docx", "json"] }];
  const properties = opts?.multiple === false ? ["openFile"] : ["openFile", "multiSelections"];
  const result = await dialog.showOpenDialog(mainWindow ?? undefined, { properties, filters });
  if (result.canceled) return [];
  const out = [];
  for (const filePath of result.filePaths) {
    const buf = readFileSync(filePath);
    if (buf.length > MAX_FILE) continue;
    const ext = extname(filePath).toLowerCase();
    out.push({
      name: basename(filePath),
      path: filePath,
      type: MIME[ext] || "application/octet-stream",
      base64: buf.toString("base64"),
    });
  }
  return out;
});
ipcMain.handle("notify", (_e, payload) => {
  if (!Notification.isSupported()) return { ok: false };
  const note = new Notification({
    title: payload?.title || "Tacite",
    body: payload?.body || "",
  });
  note.show();
  return { ok: true };
});
ipcMain.handle("set-badge", (_e, count) => {
  if (process.platform === "darwin" && app.dock) {
    app.dock.setBadge(count == null || count === "" ? "" : String(count));
  }
  return { ok: true };
});

app.setName("Tacite");
app.setAboutPanelOptions({
  applicationName: "Tacite",
  applicationVersion: app.getVersion(),
  copyright: "Intelligence presse",
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
  app.whenReady().then(async () => {
    if (process.platform === "darwin" && app.dock) {
      app.dock.setIcon(appIconPng());
    }
    loadServerOrigin();
    buildMenu();
    createWindow();
    await showSplash();
    boot();
  });
}

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", async () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
    await showSplash();
    boot();
  }
});
