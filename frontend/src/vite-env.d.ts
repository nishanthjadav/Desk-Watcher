/// <reference types="vite/client" />

// Explicit shape for the env vars we actually read, on top of Vite's
// built-in ImportMetaEnv. Keeps App.tsx honest — if it references
// `import.meta.env.SOMETHING_ELSE` we get a type error, not `any`.
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
