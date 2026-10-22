#!/usr/bin/env node
/**
 * Inspect an Expo production Android JS export without building an APK.
 *
 * Expo CLI export runs Metro, resolves all imports and bundles native JS and
 * assets. This does NOT verify an Android install, camera, network or signing.
 * Generated files stay on the CI runner; no production service is contacted.
 */
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = path.resolve(process.argv[2] || "dist-ci-android");

function allFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((item) => {
    const name = path.join(dir, item.name);
    return item.isDirectory() ? allFiles(name) : [name];
  });
}

if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
  throw new Error("Expected Android JS export directory is missing.");
}

const files = allFiles(root);
const bundles = files.filter((file) => /\.(?:hbc|js|bundle)$/i.test(file));
const assets = files.filter((file) =>
  /\.(?:png|jpe?g|webp|ttf|otf)$/i.test(file),
);

if (!bundles.length) {
  throw new Error(
    "Expo export produced no bundled JavaScript or Hermes bytecode.",
  );
}
if (!assets.length) {
  throw new Error("Expo export produced no app/image/font assets.");
}
for (const file of bundles) {
  if (fs.statSync(file).size === 0) {
    throw new Error("Expo emitted an empty application bundle.");
  }
}

// Do not echo bundle contents. Output safe counts only.
console.log(
  `Android production JS export: PASS (${bundles.length} bundle(s), ${assets.length} assets)`,
);
console.log(
  "Native APK, camera, permissions, TLS, backend reachability: NOT TESTED",
);
