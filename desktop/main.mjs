import { app, BrowserWindow, Menu, dialog, ipcMain, shell, nativeTheme } from "electron";
import { execFile } from "node:child_process";
import { copyFileSync, existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const __dirname = dirname(fileURLToPath(import.meta.url));

let webOrigin = "http://MacBook-Pro-de-MP.local:5173";
const PROJECT_NAME = "pressanalysis";
const API_IMAGE = "tacite-api:0.3.0";
const WEB_IMAGE = "tacite-web:0.3.0";
const DB_IMAGE = "pgvector/pgvector:pg16";
const STATE_FILE = () => join(app.getPath("userData"), "project-root.txt");
const CURSOR_MCP_FILE = () => join(homedir(), ".cursor", "mcp.json");

function pageUrl() {
  return `${webOrigin}/`;
}
function healthUrl() {
  return new URL("api/health", pageUrl()).href;
}
function mcpUrl() {
  return new URL("api/mcp", pageUrl()).href;
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
        detail: `Le serveur MCP « tacite » (${entry.url}) a été enregistré dans ~/.cursor/mcp.json avec ses outils et la Doctrine Press Intelligence.`,
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

function appIconPng() {
  const packaged = join(process.resourcesPath, "icon.png");
  const local = join(__dirname, "build/icon.png");
  return existsSync(packaged) ? packaged : local;
}

let mainWindow = null;
let starting = false;

function dockerEnv() {
  const extras = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    join(homedir(), ".docker/bin"),
    "/Applications/Docker.app/Contents/Resources/bin",
  ];
  return { ...process.env, PATH: `${extras.join(":")}:${process.env.PATH || ""}` };
}

function dockerBin() {
  const candidates = [
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    join(homedir(), ".docker/bin/docker"),
    "/Applications/Docker.app/Contents/Resources/bin/docker",
  ];
  return candidates.find((p) => existsSync(p)) || "docker";
}

async function runDocker(args, opts = {}) {
  return execFileAsync(dockerBin(), args, {
    env: dockerEnv(),
    timeout: opts.timeout ?? 180_000,
    maxBuffer: 20_000_000,
    cwd: opts.cwd,
  });
}

function sendStatus(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("status", payload);
  }
}

function isComposeRoot(dir) {
  return dir && existsSync(join(dir, "docker-compose.yml"));
}

function stackDir() {
  if (app.isPackaged) return join(process.resourcesPath, "stack");
  const fromSource = join(__dirname, "..");
  if (isComposeRoot(fromSource)) return fromSource;
  return join(process.resourcesPath, "stack");
}

function discoverEnvSource() {
  const candidates = [];
  try {
    const saved = readFileSync(STATE_FILE(), "utf8").trim();
    if (saved) candidates.push(join(saved, ".env"));
  } catch { /* pas encore de dossier enregistré */ }
  candidates.push(join(__dirname, "..", ".env"));
  return candidates.find((p) => existsSync(p)) || null;
}

function ensureEnvFile() {
  const dest = join(app.getPath("userData"), "stack.env");
  if (!existsSync(dest)) {
    mkdirSync(app.getPath("userData"), { recursive: true });
    const src = discoverEnvSource();
    if (src) copyFileSync(src, dest);
    else writeFileSync(dest, "LLM_API_KEY=\nLLM_BASE_URL=https://inference.aleria.com/v1\n");
  }
  return dest;
}

async function hasImage(name) {
  try {
    await runDocker(["image", "inspect", name], { timeout: 15_000 });
    return true;
  } catch {
    return false;
  }
}

async function waitFor(url, timeoutMs, ok = (r) => r.ok) {
  const start = Date.now();
  let last = "";
  while (Date.now() - start < timeoutMs) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(2500) });
      if (ok(r)) return;
      last = `HTTP ${r.status}`;
    } catch (e) {
      last = e.cause?.code || e.message || "injoignable";
    }
    await new Promise((r) => setTimeout(r, 800));
  }
  throw new Error(`Pas de réponse (${last})`);
}

async function ensureDocker() {
  try {
    await runDocker(["info"], { timeout: 8000 });
    return;
  } catch {
    sendStatus({ message: "Ouverture de Docker Desktop…" });
    await execFileAsync("open", ["-a", "Docker"], { timeout: 10_000 }).catch(() => {
      throw new Error("Docker Desktop est introuvable. Installez-le, puis réessayez.");
    });
  }
  const start = Date.now();
  while (Date.now() - start < 90_000) {
    try {
      await runDocker(["info"], { timeout: 5000 });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
  throw new Error("Docker Desktop ne répond pas. Ouvrez-le, attendez le témoin vert, puis réessayez.");
}

async function startStack(root) {
  const local = (await hasImage(API_IMAGE)) && (await hasImage(WEB_IMAGE)) && (await hasImage(DB_IMAGE));
  if (local) sendStatus({ message: "Démarrage de Tacite sur cet ordinateur…" });
  else sendStatus({ message: "Installation de Tacite sur cet ordinateur. La première fois peut prendre un moment…" });
  const args = [
    "compose",
    "--env-file", ensureEnvFile(),
    "-f", join(root, "docker-compose.yml"),
    "-p", PROJECT_NAME,
    "up", "-d",
  ];
  if (local) args.push("--pull", "never");
  else args.push("--build");
  await runDocker(args, { cwd: root, timeout: 1_800_000 });
  sendStatus({ message: "Attente de l’interface…" });
  await waitFor(healthUrl(), 180_000);
  await waitFor(pageUrl(), 60_000);
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
    sendStatus({ message: "Connexion à la base Tacite…" });
    await waitFor(healthUrl(), 20_000);
    if (mainWindow && !mainWindow.isDestroyed()) await mainWindow.loadURL(pageUrl());
  } catch (e) {
    sendStatus({
      error: true,
      idle: true,
      message: "La base Tacite est injoignable. Le serveur commun doit être allumé.",
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
              label: "Preferences",
              submenu: [
                {
                  label: "Paramètres de Tacite…",
                  accelerator: "CmdOrCtrl+,",
                  click: () => {
                    if (mainWindow && !mainWindow.isDestroyed()) {
                      mainWindow.loadURL(`${pageUrl()}settings`);
                    }
                  },
                },
                { type: "separator" },
                {
                  label: "Connecter à Cursor (MCP)…",
                  click: () => connectToCursor({ showDialog: true }),
                },
              ],
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
ipcMain.handle("connect-cursor", (_e, opts) => connectToCursor(opts));

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
