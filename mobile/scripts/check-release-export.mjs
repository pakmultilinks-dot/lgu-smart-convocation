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
import { fileURLToPath } from "node:url";

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
// Expo 57 Android exports put native JS into _expo/static/js/android/*.hbc.
// Image/font assets are resolved during Metro export, but may be referenced
// by hashed/extensionless names or metadata instead of .png/.ttf filenames.
// Therefore validate the actual bundle + metadata, and the source asset
// inputs required by app.json, without assuming an output filename format.
const manifest = path.join(root, "metadata.json");
if (!fs.existsSync(manifest) || fs.statSync(manifest).size === 0) {
  throw new Error("Expo export produced no metadata.json.");
}
JSON.parse(fs.readFileSync(manifest, "utf8"));
const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const expectedSourceAssets = [
  "assets/icon.png",
  "assets/adaptive-icon.png",
  "assets/splash.png",
  "assets/lgu-logo.png",
];
for (const asset of expectedSourceAssets) {
  const name = path.join(sourceRoot, asset);
  if (!fs.existsSync(name) || fs.statSync(name).size === 0) {
    throw new Error("Required source asset missing: " + asset);
  }
}
if (!bundles.length) {
  throw new Error(
    "Expo export produced no bundled JavaScript or Hermes bytecode.",
  );
}
for (const file of bundles) {
  if (fs.statSync(file).size === 0) {
    throw new Error("Expo emitted an empty application bundle.");
  }
}

// Do not echo bundle contents. Output safe counts only.
console.log(
  `Android production JS export: PASS (${bundles.length} bundle(s), valid metadata, ${expectedSourceAssets.length} required source assets)`,
);
console.log(
  "Native APK, camera, permissions, TLS, backend reachability: NOT TESTED",
);
