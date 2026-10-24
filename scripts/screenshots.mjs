// Capture the screenshots used in the docs from a running OpenPipeline server.
//
//   openpipeline demo --port 8484          # in one terminal
//   node scripts/screenshots.mjs           # in another; PNGs go to docs/assets
//
// Usage: node scripts/screenshots.mjs [URL] [OUT_DIR]
// Needs the `playwright` package and a Chromium it can launch. It builds nothing and
// changes nothing in the project: it only looks at the pages.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
function loadPlaywright() {
  for (const where of [undefined, process.env.NODE_PATH, "/opt/node22/lib/node_modules"]) {
    try {
      return where ? require(require.resolve("playwright", { paths: [where] })) : require("playwright");
    } catch {
      // Try the next place.
    }
  }
  throw new Error("Could not find the playwright package. Install it with: npm i -g playwright");
}

const { chromium } = loadPlaywright();
const url = (process.argv[2] ?? "http://127.0.0.1:8484").replace(/\/$/, "");
const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(process.argv[3] ?? resolve(here, "../docs/assets"));
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 820 }, deviceScaleFactor: 1 });
const shot = async (name) => {
  await page.waitForTimeout(700); // Let the graph finish laying out and animating.
  await page.screenshot({ path: resolve(out, `${name}.png`), type: "png" });
  console.log(`wrote ${name}.png`);
};

await page.goto(url);
await page.waitForSelector(".pnode");
await shot("graph");

await page.locator(".pnode", { hasText: "customers" }).first().click();
await page.getByRole("region", { name: /About customers/ }).waitFor();
await shot("story");

await page.getByRole("button", { name: /^Rules/ }).click();
await page.waitForSelector("text=Lifetime value is what a customer has paid");
await shot("rules");

await page.getByRole("button", { name: /^Proposals/ }).click();
await page.getByRole("button", { name: "Show on graph" }).click();
await page.waitForSelector(".pnode--added");
await shot("review");

await browser.close();
