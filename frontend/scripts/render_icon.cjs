// Rasterize public/logo.svg into PNG sizes and a multi-resolution Windows .ico.
// Run with: npx electron scripts/render_icon.cjs

const { app, BrowserWindow } = require("electron");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SVG_PATH = path.join(ROOT, "public", "logo.svg");
const ASSETS = path.join(ROOT, "assets");
const SIZES = [16, 24, 32, 48, 64, 128, 256];

function writeIco(entries, target) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(entries.length, 4);

  const dirs = [];
  let offset = 6 + entries.length * 16;
  for (const entry of entries) {
    const dir = Buffer.alloc(16);
    dir.writeUInt8(entry.size >= 256 ? 0 : entry.size, 0);
    dir.writeUInt8(entry.size >= 256 ? 0 : entry.size, 1);
    dir.writeUInt8(0, 2); // palette
    dir.writeUInt8(0, 3); // reserved
    dir.writeUInt16LE(1, 4); // planes
    dir.writeUInt16LE(32, 6); // bpp
    dir.writeUInt32LE(entry.png.length, 8);
    dir.writeUInt32LE(offset, 12);
    offset += entry.png.length;
    dirs.push(dir);
  }

  fs.writeFileSync(target, Buffer.concat([header, ...dirs, ...entries.map((e) => e.png)]));
}

app.whenReady().then(async () => {
  fs.mkdirSync(ASSETS, { recursive: true });
  const svg = fs.readFileSync(SVG_PATH, "utf8");
  const data = Buffer.from(svg).toString("base64");
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;padding:0;width:512px;height:512px;overflow:hidden;background:transparent}
    img{display:block;width:512px;height:512px}
  </style></head><body>
    <img src="data:image/svg+xml;base64,${data}" />
  </body></html>`;

  const win = new BrowserWindow({
    width: 512,
    height: 512,
    useContentSize: true,
    show: false,
    frame: false,
    transparent: true,
    webPreferences: { offscreen: true },
  });

  await win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
  await new Promise((resolve) => setTimeout(resolve, 900));

  const image = await win.webContents.capturePage();
  const size = image.getSize();
  console.log(`captured ${size.width}x${size.height}`);
  const png = image.toPNG();
  if (png.length < 1000) {
    throw new Error("capture produced an empty image");
  }
  fs.writeFileSync(path.join(ASSETS, "logo-512.png"), png);

  const entries = [];
  for (const size of SIZES) {
    const resized = image.resize({ width: size, height: size, quality: "best" });
    const png = resized.toPNG();
    entries.push({ size, png });
    if (size === 256) fs.writeFileSync(path.join(ASSETS, "logo-256.png"), png);
  }

  writeIco(entries, path.join(ASSETS, "icon.ico"));
  console.log(`Wrote ${path.join(ASSETS, "icon.ico")} with sizes ${SIZES.join(",")}`);
  app.quit();
}).catch((error) => {
  console.error(error);
  app.exit(1);
});
