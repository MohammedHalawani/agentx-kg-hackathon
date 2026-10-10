/// <reference types="vite/client" />
interface ImportMetaEnv {
  /** "lab" runs the original browser-only UI lab on fixtures. Anything else connects to the backend. */
  readonly VITE_SUHAIL_DATA?: string;
  /** Backend origin for the API. Empty: the page's own origin (the backend serves this app). */
  readonly VITE_SUHAIL_API?: string;
}
