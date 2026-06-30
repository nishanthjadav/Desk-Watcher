/** @type {import('tailwindcss').Config} */
// Design tokens mirror frontend/tailwind.config.js so the landing page reads
// as a natural extension of the app. If you change a color here, change it
// in the frontend too (or move them to a shared file when the project grows).
export default {
  content: ["./src/**/*.{astro,html,ts,tsx,js,jsx,md,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0908", // page background
          900: "#11100e", // panel background
          850: "#161513", // hover lift
          800: "#1c1a17", // dividers
          700: "#26231f", // primary borders
          600: "#33302a",
          500: "#4a4540",
          400: "#6b655d", // tertiary text
          300: "#8f897f", // secondary text / panel titles
          200: "#b5afa4",
          100: "#dcd6c9", // primary body text
        },
        amber: {
          50: "#fef8e7",
          100: "#fdecc4",
          200: "#fbd887",
          300: "#f7c04a",
          400: "#f5a623", // brand accent (wordmark, hover state)
          500: "#e08a0c",
          600: "#b86d07", // filled buttons, active states
          700: "#8a5106",
          800: "#5c3604",
          900: "#3a2202",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Cascadia Mono",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        // Signature small-label size used everywhere in the dashboard.
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
};
