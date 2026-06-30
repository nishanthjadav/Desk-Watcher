// Copies the project screenshots from /screenshots (at the repo root) into
// site/public so Astro can serve them. Also copies the overall-dashboard
// shot to site/public/og.png for social-share previews.
//
// Runs automatically as `predev` and `prebuild` via package.json. Safe to
// run manually anytime — it's idempotent.
import { copyFileSync, mkdirSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "..", "..", "screenshots");
const dstDir = resolve(here, "..", "public", "screenshots");
const ogPath = resolve(here, "..", "public", "og.png");
const heroShot = "overall-dashboard.png";

if (!existsSync(src)) {
  console.error(`[sync-screenshots] source not found: ${src}`);
  console.error(
    "Drop your dashboard screenshots into /screenshots at the repo root and try again."
  );
  process.exit(1);
}

mkdirSync(dstDir, { recursive: true });

const files = readdirSync(src).filter((f) => /\.(png|jpe?g|webp|avif)$/i.test(f));
for (const f of files) {
  copyFileSync(join(src, f), join(dstDir, f));
}

const heroSrc = join(src, heroShot);
if (existsSync(heroSrc)) {
  copyFileSync(heroSrc, ogPath);
}

console.log(
  `[sync-screenshots] copied ${files.length} file(s) to public/screenshots/` +
    (existsSync(heroSrc) ? ` and refreshed og.png` : "")
);
