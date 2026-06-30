import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";

// `site` is used for canonical URLs and absolute OG image URLs.
// Update this once Vercel assigns the final subdomain (or once a custom
// domain is attached) and redeploy so canonical/OG tags resolve correctly.
export default defineConfig({
  site: "https://desk-watcher.vercel.app",
  integrations: [tailwind({ applyBaseStyles: false })],
  trailingSlash: "ignore",
  build: { inlineStylesheets: "auto" },
});
