import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const config = require("../app.config.js");
const { expo } = JSON.parse(readFileSync(new URL("../app.json", import.meta.url)));
const original = process.env.APP_VARIANT;
try {
  for (const variant of ["preview", "production", "development"]) {
    process.env.APP_VARIANT = variant;
    const result = config({ config: expo });
    assert.equal(result.name, "LGU Convocation");
    assert.equal(result.android.package, variant === "preview"
      ? "pk.edu.lgu.smartconvocation.preview" : "pk.edu.lgu.smartconvocation");
  }
  console.log("PASS: every build uses LGU Convocation and preserves its package identity");
} finally {
  if (original === undefined) delete process.env.APP_VARIANT;
  else process.env.APP_VARIANT = original;
}
