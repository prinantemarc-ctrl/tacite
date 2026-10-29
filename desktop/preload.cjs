const { contextBridge, ipcRenderer } = require("electron");

function listen(channel, cb) {
  const listener = (_e, payload) => cb(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("tacite", {
  isDesktop: true,
  platform: process.platform,
  onStatus: (cb) => listen("status", cb),
  onMenu: (cb) => listen("menu", cb),
  retry: () => ipcRenderer.invoke("retry"),
  connectCursor: (opts) => ipcRenderer.invoke("connect-cursor", opts),
  getInfo: () => ipcRenderer.invoke("app-info"),
  openFiles: (opts) => ipcRenderer.invoke("open-files", opts),
  showNotification: (title, body) => ipcRenderer.invoke("notify", { title, body }),
  setBadge: (count) => ipcRenderer.invoke("set-badge", count),
});
