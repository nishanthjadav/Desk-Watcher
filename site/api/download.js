// Zero-maintenance download redirect.
//
// The landing page links to /api/download?os=mac (or ?os=win) instead of a
// hard-coded GitHub Releases asset URL. This function asks GitHub for the
// LATEST release and 302-redirects to the matching installer asset, so a new
// release never requires editing any link — the version-stamped filename
// (e.g. Desk.Watcher_0.2.0_aarch64.dmg) is discovered at request time.
//
// Deployed as a standalone Vercel serverless function (Vercel auto-detects the
// api/ directory). Intentionally NOT an Astro endpoint: the site is a static
// build with no SSR adapter, and keeping this outside Astro avoids pulling one
// in just for a redirect.

const REPO = "nishanthjadav/Desk-Watcher";

// Map ?os= value → predicate that picks its installer asset from the release.
// endsWith on the extension survives filename changes (version bumps, and even
// a future universal build like ...universal.dmg still ends in .dmg).
const MATCHERS = {
  mac: (name) => name.endsWith(".dmg"),
  win: (name) => name.endsWith(".msi"),
};

export default async function handler(req, res) {
  const os = String(req.query.os || "").toLowerCase();
  const match = MATCHERS[os];
  if (!match) {
    res.status(400).json({ error: "pass ?os=mac or ?os=win" });
    return;
  }

  try {
    const r = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: {
        Accept: "application/vnd.github+json",
        "User-Agent": "desk-watcher-site",
      },
    });
    if (!r.ok) {
      // Rate-limited (60/hr/IP unauthenticated) or transient GitHub error —
      // don't leave the user stuck; send them to the releases page as a
      // fallback where they can grab the asset manually.
      res.setHeader("Location", `https://github.com/${REPO}/releases/latest`);
      res.status(302).end();
      return;
    }

    const release = await r.json();
    const asset = (release.assets || []).find((a) => match(a.name));
    if (!asset) {
      // Release exists but has no asset of this type yet (e.g. Mac build not
      // attached to this version). Fall back to the release page.
      res.setHeader("Location", release.html_url || `https://github.com/${REPO}/releases/latest`);
      res.status(302).end();
      return;
    }

    // Cache the redirect at the edge for 10 min so a burst of clicks doesn't
    // spend the unauthenticated GitHub rate limit. The target asset URL is
    // stable for a given release, so short caching is safe.
    res.setHeader("Cache-Control", "public, max-age=0, s-maxage=600");
    res.setHeader("Location", asset.browser_download_url);
    res.status(302).end();
  } catch {
    res.setHeader("Location", `https://github.com/${REPO}/releases/latest`);
    res.status(302).end();
  }
}
