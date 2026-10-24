// Capture the screenshots used in the docs from a running OpenPipeline server.
//
//   openpipeline demo --port 8484          # in one terminal
//   node scripts/screenshots.mjs           # in another; PNGs go to docs/assets
//
// Run `pnpm build` first so the server has a UI to serve.
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

// Search: open the box with the keyboard and show some results.
await page.keyboard.press("Escape");
await page.keyboard.press("/");
await page.getByRole("combobox", { name: /Search/ }).fill("amount");
await page.getByRole("option").first().waitFor();
await shot("search");
await page.getByRole("combobox", { name: /Search/ }).fill("");
await page.keyboard.press("Escape");

await page.locator(".pnode", { hasText: "customers" }).first().click();
await page.getByRole("region", { name: /About customers/ }).waitFor();
await shot("story");

// Sample rows: open the section and scroll the side panel so the table is in view.
await page.getByRole("button", { name: /Sample rows/ }).click();
await page.locator(".sample__table tbody tr").first().waitFor();
await page.locator(".sample").evaluate((el) => el.scrollIntoView({ block: "end" }));
await shot("sample-rows");

// Column lineage: pick a column, then scroll the panel to show where it comes from.
await page.locator(".sample__toggle").click(); // Collapse again to keep the panel short.
await page
  .getByRole("region", { name: "Column lineage" })
  .getByRole("button", { name: "lifetime_value", exact: true })
  .click();
await page.waitForSelector(".collineage__ref");
await page
  .getByRole("region", { name: "Column lineage" })
  .evaluate((el) => el.scrollIntoView({ block: "start" }));
await shot("lineage");

// Click empty graph space to clear the selection before the next pages.
await page.locator(".react-flow__pane").click({ position: { x: 600, y: 120 } });
await page.getByRole("button", { name: /^Rules/ }).click();
await page.waitForSelector("text=Lifetime value is what a customer has paid");
await page.locator(".side").evaluate((el) => el.scrollTo(0, 0));
await shot("rules");

await page.getByRole("button", { name: /^Proposals/ }).click();
await page.getByRole("button", { name: "Show on graph" }).click();
await page.waitForSelector(".pnode--added");
await shot("review");

await browser.close();
