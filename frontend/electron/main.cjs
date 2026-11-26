const { app, BrowserWindow, shell } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

const PORT = Number(process.env.CLOUDPILOT_PORT || 8000);
const BASE_URL = `http://127.0.0.1:${PORT}`;

let backendProc = null;
let mainWindow = null;

function firstExisting(paths) {
  for (const p of paths) {
    try {
      if (p && fs.existsSync(p)) return p;
    } catch (_) {
      /* ignore */
    }
  }
  return null;
}

function resolveBackendDir() {
  const candidates = app.isPackaged
    ? [
        path.resolve(process.resourcesPath || "", "backend"), // packaged extraResources
        path.resolve(__dirname, "..", "..", "backend"),
      ]
    : [
        path.resolve(__dirname, "..", "..", "backend"), // repo layout
        path.resolve(process.resourcesPath || "", "backend"),
      ];
  return firstExisting(candidates) || path.resolve(__dirname, "..", "..", "backend");
}

function resolvePython(backendDir) {
  if (process.env.CLOUDPILOT_PYTHON) return process.env.CLOUDPILOT_PYTHON;
  const venv = path.resolve(backendDir, "..", ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venv)) return venv;
  const bundled = path.resolve(process.resourcesPath || "", "python", "python.exe");
  if (fs.existsSync(bundled)) return bundled;
  return "python";
}

function startBackend() {
  if (process.env.CLOUDPILOT_NO_BACKEND === "1") return;
  const backendDir = resolveBackendDir();
  const python = resolvePython(backendDir);

  const env = { ...process.env };
  // An embedded interpreter must not inherit the host's user-site packages.
  const bundledPythonDir = path.resolve(process.resourcesPath || "", "python");
  if (python.toLowerCase().startsWith(bundledPythonDir.toLowerCase())) {
    env.PYTHONNOUSERSITE = "1";
  }
  if (app.isPackaged) {
    // Writable database and bundled SPA location inside the installed app.
    env.CLOUDPILOT_DB = path.join(app.getPath("userData"), "cloudpilot.db");
    env.CLOUDPILOT_FRONTEND_DIST = path.join(process.resourcesPath, "frontend", "dist");
  }

  try {
    backendProc = spawn(
      python,
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(PORT)],
      { cwd: backendDir, env, stdio: "ignore", windowsHide: true }
    );
    backendProc.on("error", () => {
      /* surfaced through health polling */
    });
  } catch (_) {
    backendProc = null;
  }
}

function waitForHealth(timeoutMs = 20000) {
  const started = Date.now();
  return new Promise((resolve) => {
    const attempt = () => {
      const req = http.get(`${BASE_URL}/api/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve(true);
        retry();
      });
      req.on("error", retry);
      req.setTimeout(1200, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) return resolve(false);
      setTimeout(attempt, 400);
    };
    attempt();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1024,
    minHeight: 720,
    title: "CloudPilot AI",
    backgroundColor: "#0b1220",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  await waitForHealth();
  mainWindow.loadURL(BASE_URL);
}

app.whenReady().then(() => {
  startBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function stopBackend() {
  if (backendProc) {
    try {
      backendProc.kill();
    } catch (_) {
      /* ignore */
    }
    backendProc = null;
  }
}

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", stopBackend);
