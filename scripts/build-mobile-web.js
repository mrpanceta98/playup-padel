const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const dist = path.join(root, "dist");
const frontend = path.join(root, "frontend");
const assets = path.join(root, "assets");
const productionApiBaseUrl = "https://playup-padel-ob3c.onrender.com";
const apiBaseUrl = (process.env.PLAYUP_API_BASE_URL || productionApiBaseUrl).replace(/\/+$/, "");

function copyDirectory(from, to) {
  fs.mkdirSync(to, { recursive: true });
  fs.cpSync(from, to, { recursive: true });
}

fs.rmSync(dist, { recursive: true, force: true });
copyDirectory(frontend, dist);
copyDirectory(assets, path.join(dist, "assets"));

const indexPath = path.join(dist, "index.html");
let index = fs.readFileSync(indexPath, "utf8");
index = index.replace(
  /<meta name="playup-api-base-url" content="[^"]*" \/>/,
  `<meta name="playup-api-base-url" content="${apiBaseUrl}" />`
);
fs.writeFileSync(indexPath, index);

console.log(`Prepared Capacitor web bundle in dist/ with API_BASE_URL=${apiBaseUrl || "(same origin)"}`);
