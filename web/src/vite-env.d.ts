/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Base URL of the BuyBox Matcher backend API.
   * This is the ONLY external reference the frontend is permitted to hold
   * (Requirement 14.2). No AI provider or database credentials are ever
   * present in the frontend.
   */
  readonly VITE_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
