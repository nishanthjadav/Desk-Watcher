# desk-watcher landing page

The marketing site for the desk-watcher project. Astro + Tailwind, deployed to Vercel.

```bash
cd site
npm install
npm run dev      # http://localhost:4321
npm run build    # → dist/
```

## Layout

- `src/pages/index.astro` — the landing page.
- `src/pages/privacy.astro` — the privacy note.
- `src/layouts/Base.astro` — HTML shell + `<head>` + meta tags.
- `src/components/` — Header (live clock), Footer, SectionFrame (Panel.tsx echo).
- `src/styles/global.css` — Tailwind directives + the one caret-blink keyframe.
- `tailwind.config.mjs` — mirrors `frontend/tailwind.config.js` (same `ink-*` / `amber-*` tokens, same `text-2xs` size, same system font stacks).

## Screenshots

The hero and feature shots live at `/screenshots/` at the **repo root** (not in this directory). On every `npm run dev` / `npm run build`, `scripts/sync-screenshots.mjs` copies them into `public/screenshots/` and also copies `overall-dashboard.png` to `public/og.png` for social previews.

To update a screenshot: replace the file in `../screenshots/` and rebuild.

## Deploy

Vercel via the GitHub integration:

1. **New Project** → import this repo.
2. Set **Root Directory** to `site`.
3. Astro is auto-detected — accept the defaults.
4. Deploy. Vercel assigns a free `*.vercel.app` subdomain.
5. Update `site:` in `astro.config.mjs` to the assigned URL (so canonical and OG tags resolve correctly), commit, and redeploy.

Every push to `main` triggers a redeploy. PRs get preview deploys at unique URLs.
