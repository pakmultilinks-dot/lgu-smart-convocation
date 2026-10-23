#!/usr/bin/env node
// Expo Go and its API must be running together for QR testing to work.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const mobile = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.dirname(mobile);
const venv = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.LGU_PYTHON || (existsSync(venv) ? venv : "python");
const backend = spawn(python, [path.join(root, "app/scripts/run_local_mobile.py")], {
  cwd: root, stdio: "inherit", env: process.env,
});
let metro;
const stop = () => { metro?.kill(); backend.kill(); };
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
backend.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
backend.on("exit", (code) => { metro?.kill(); process.exitCode = code ?? 1; });
let healthy = false;
for (let attempt = 0; attempt < 60 && backend.exitCode === null; attempt++) {
  try {
    const response = await fetch("http://127.0.0.1:5000/api/health", { signal: AbortSignal.timeout(1000) });
    const body = await response.json();
    if (response.ok && body.ok === true && body.app === "LGU Smart Convocation") {
      healthy = true;
      break;
    }
  } catch { /* Backend is still starting. */ }
  await new Promise((resolve) => setTimeout(resolve, 500));
}
if (!healthy || backend.exitCode !== null) {
  console.error("Local backend could not start. Check Python dependencies and port 5000 above.");
  stop();
  process.exitCode = 1;
} else {
  console.log("Backend ready. Scan the Expo QR with your phone on the same Wi-Fi.");
  metro = spawn(process.execPath, [path.join(mobile, "node_modules/expo/bin/cli"), "start", "--go", "--lan", ...process.argv.slice(2)], {
    cwd: mobile, stdio: "inherit", env: process.env,
  });
  metro.on("exit", (code) => { backend.kill(); process.exitCode = code ?? 0; });
}
