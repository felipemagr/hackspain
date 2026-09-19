import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const web = fileURLToPath(new URL("../", import.meta.url));
const environment = { ...process.env, VITE_API_URL: process.env.VITE_API_URL ?? "http://127.0.0.1:8000" };
for (const args of [
  ["node_modules/typescript/bin/tsc", "-b"],
  ["node_modules/vite/bin/vite.js", "build", "--outDir", "../data/processed/v3-web", "--base", "./"],
]) {
  const result = spawnSync(process.execPath, args, { cwd: web, env: environment, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
const source = new URL("../../data/processed/v3-web/xray-v3.html", import.meta.url);
const destination = new URL("../../data/processed/xray-v3.html", import.meta.url);
const html = readFileSync(source, "utf8")
  .replaceAll('"./assets/', '"./v3-web/assets/')
  .replaceAll('"./favicon.svg"', '"./v3-web/favicon.svg"');
writeFileSync(destination, html);
console.log(`Published ${fileURLToPath(destination)}`);
