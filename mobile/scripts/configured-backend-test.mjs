import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const configure = require("../app.config.js");
const previous = process.env.APP_VARIANT;
process.env.APP_VARIANT = "preview";
const preview = configure({ config: { extra: { existing: true } } });
process.env.APP_VARIANT = "production";
assert.equal(configure({ config: { extra: {} } }).extra.apiBaseUrl, undefined);
if (previous === undefined) delete process.env.APP_VARIANT;
else process.env.APP_VARIANT = previous;
assert.equal(preview.extra.existing, true);
assert.equal(preview.extra.apiBaseUrl, "https://lguconvocationpk.pythonanywhere.com");

const stored = new Map();
const constants = { executionEnvironment: "standalone", expoConfig: { extra: preview.extra } };
const output = ts.transpileModule(readFileSync(new URL("../src/store/settings.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
const exported = {};
vm.runInNewContext(output, {
  exports: exported, __DEV__: false,
  require(name) {
    if (name === "expo-constants") return constants;
    if (name === "@react-native-async-storage/async-storage") return { getItem: async key => stored.get(key) ?? null };
    return {};
  },
});
assert.equal(await exported.getApiBaseUrl(), preview.extra.apiBaseUrl);
stored.set("lgu.api_base_url", "https://explicit.example");
stored.set("lgu.api_base_url_mode", "custom");
assert.equal(await exported.getApiBaseUrl(), "https://explicit.example");
stored.clear();
constants.expoConfig.extra = { apiBaseUrl: "http://insecure.example" };
assert.equal(await exported.getApiBaseUrl(), "");
constants.expoConfig.extra = {};
assert.equal(await exported.getApiBaseUrl(), "");
console.log("PASS: fresh preview HTTPS default, custom server precedence, unconfigured production, invalid default rejected");
