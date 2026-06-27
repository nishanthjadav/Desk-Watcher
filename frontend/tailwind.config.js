/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0908",
          900: "#11100e",
          850: "#161513",
          800: "#1c1a17",
          700: "#26231f",
          600: "#33302a",
          500: "#4a4540",
          400: "#6b655d",
          300: "#8f897f",
          200: "#b5afa4",
          100: "#dcd6c9",
        },
        amber: {
          50:  "#fef8e7",
          100: "#fdecc4",
          200: "#fbd887",
          300: "#f7c04a",
          400: "#f5a623",
          500: "#e08a0c",
          600: "#b86d07",
          700: "#8a5106",
          800: "#5c3604",
          900: "#3a2202",
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Cascadia Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
};
