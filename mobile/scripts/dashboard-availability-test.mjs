// Exercise real TS modules with controlled network, focus and app lifecycle.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(file, mocks, globals = {}) {
  const exports = {};
  const source = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, require: (id) => {
    assert(id in mocks, `Unexpected dependency ${id}`); return mocks[id];
  }, setTimeout, clearTimeout, AbortController, console, __DEV__: false, ...globals });
  return exports;
}

let responseBody;
const api = load("../src/api/client.ts", {
  "../store/settings": { getApiBaseUrl: async () => "http://test.local" },
  "../store/adminAccess": {}, "../store/scannerSession": {},
}, { fetch: async () => ({ ok: true, json: async () => responseBody }) });
for (const body of [null, {}, { student: false, volunteer: true, liveboard: true },
  { student: true, volunteer: "true", liveboard: false }]) {
  responseBody = body;
  await assert.rejects(api.fetchDashboardAccess(), (error) => error.status === 502);
}
responseBody = { student: true, volunteer: false, liveboard: true };
assert.equal((await api.fetchDashboardAccess()).volunteer, false);

const state = [];
let cursor = 0, focus, cleanup, tick, onAppState, resolve, reject, calls = 0;
let intervalCleared = false, listenerRemoved = false;
const appState = { currentState: "active", addEventListener: (_, listener) => {
  onAppState = listener; return { remove: () => { listenerRemoved = true; } };
} };
const hook = load("../src/hooks/useDashboardAvailability.ts", {
  "react": {
    useState: (initial) => { const index = cursor++; if (!(index in state)) state[index] = initial;
      return [state[index], (next) => { state[index] = typeof next === "function" ? next(state[index]) : next; }]; },
    useCallback: (fn) => fn,
  },
  "expo-router": { useFocusEffect: (fn) => { focus = fn; } },
  "react-native": { AppState: appState },
  "../api/client": { fetchDashboardAccess: () => { calls++;
    return new Promise((yes, no) => { resolve = yes; reject = no; }); } },
}, { setInterval: (fn) => { tick = fn; return 1; }, clearInterval: () => { intervalCleared = true; } });
hook.useDashboardAvailability(); cleanup = focus();
assert.equal(calls, 1);
tick(); assert.equal(calls, 1, "Never overlap network requests");
resolve({ student: true, volunteer: true, liveboard: false });
await new Promise(setImmediate);
assert.equal(state[1], "online"); assert.equal(state[0].liveboard, false);
appState.currentState = "background"; tick(); assert.equal(calls, 1);
appState.currentState = "inactive"; tick(); assert.equal(calls, 1);
appState.currentState = "active"; onAppState("active"); assert.equal(calls, 2);
reject(new Error("Offline")); await new Promise(setImmediate);
assert.equal(state[1], "offline"); assert.equal(state[0].volunteer, true, "Preserve last known access offline");
tick(); assert.equal(calls, 3);
cleanup(); assert(intervalCleared && listenerRemoved);
resolve({ student: true, volunteer: false, liveboard: true });
await new Promise(setImmediate);
assert.equal(state[0].volunteer, true, "Ignore responses after unmount");
console.log("PASS: validated access responses, one request at a time, background pause, foreground refresh, offline retention and cleanup");
