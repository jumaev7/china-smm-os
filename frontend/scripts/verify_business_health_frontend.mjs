/**
 * Frontend Business Health presentation helper checks.
 * Run from frontend/: node scripts/verify_business_health_frontend.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");

function bandFromScore(score) {
  if (score >= 85) return "excellent";
  if (score >= 70) return "healthy";
  if (score >= 50) return "needs_attention";
  if (score >= 30) return "at_risk";
  return "critical";
}

assert.equal(bandFromScore(100), "excellent");
assert.equal(bandFromScore(85), "excellent");
assert.equal(bandFromScore(84), "healthy");
assert.equal(bandFromScore(70), "healthy");
assert.equal(bandFromScore(69), "needs_attention");
assert.equal(bandFromScore(50), "needs_attention");
assert.equal(bandFromScore(49), "at_risk");
assert.equal(bandFromScore(30), "at_risk");
assert.equal(bandFromScore(29), "critical");
assert.equal(bandFromScore(0), "critical");

const helperSrc = fs.readFileSync(path.join(root, "lib", "business-health.ts"), "utf8");
assert.match(helperSrc, /businessHealthBandFromScore/);
assert.match(helperSrc, /domainDrilldownHref/);
assert.match(helperSrc, /\/advertising/);

const componentSrc = fs.readFileSync(
  path.join(root, "components", "executive", "BusinessHealthBreakdown.tsx"),
  "utf8",
);
assert.match(componentSrc, /Main deductions/);
assert.match(componentSrc, /Positive signals/);
assert.match(componentSrc, /Unavailable|unavailable/);
assert.match(componentSrc, /aria-label/);
assert.match(componentSrc, /loading/);
assert.match(componentSrc, /Business health assessment unavailable/);

const apiSrc = fs.readFileSync(path.join(root, "lib", "api.ts"), "utf8");
assert.match(apiSrc, /export interface BusinessHealthAssessment/);
assert.match(apiSrc, /business_health\?: BusinessHealthAssessment/);

const dashSrc = fs.readFileSync(
  path.join(root, "app", "(dashboard)", "dashboard", "page.tsx"),
  "utf8",
);
assert.match(dashSrc, /BusinessHealthBreakdown/);

const execSrc = fs.readFileSync(
  path.join(root, "app", "(dashboard)", "executive-copilot", "page.tsx"),
  "utf8",
);
assert.match(execSrc, /BusinessHealthBreakdown/);
assert.match(execSrc, /business_health/);

console.log("OK business-health frontend checks");
