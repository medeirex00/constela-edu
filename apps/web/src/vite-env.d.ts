/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base absoluta da API (usada nos builds desktop/Tauri; no web fica vazio e o proxy resolve). */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
