import assert from "node:assert/strict";
import fs from "node:fs";

const caddy = fs.readFileSync(
  new URL("../deploy/Caddyfile", import.meta.url),
  "utf8",
);
const html = fs.readFileSync(
  new URL("../web/index.html", import.meta.url),
  "utf8",
);

const policy = caddy.match(/Content-Security-Policy "([^"]+)"/)?.[1] ?? "";
assert.match(policy, /default-src 'none'/);
assert.match(policy, /script-src 'self' 'wasm-unsafe-eval'/);
assert.doesNotMatch(policy, /script-src[^;]*'unsafe-inline'/);
assert.doesNotMatch(policy, /script-src[^;]*'unsafe-eval'/);
assert.match(policy, /frame-ancestors 'none'/);
assert.match(policy, /object-src 'none'/);
assert.match(policy, /base-uri 'none'/);
assert.match(policy, /form-action 'self'/);
assert.doesNotMatch(html, /\son[a-z]+\s*=/i);
assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/i);

console.log("CSP contract tests passed");
