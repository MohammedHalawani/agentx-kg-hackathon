/**
 * Data source for this build.
 *
 * "backend" (default): every case, event, decision and outcome comes from the Suhail API.
 * "lab": the original browser-only UI lab on local fixtures, kept for design work and for
 * visual regression against the standalone lab. Lab code is loaded only in lab builds.
 */
export const LAB = import.meta.env.VITE_SUHAIL_DATA === "lab";
export const API_ORIGIN = import.meta.env.VITE_SUHAIL_API ?? "";
/** Router base without a trailing slash ("/app" when served by the backend, "" in the lab). */
export const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, "");
export const asset = (name: string) => `${import.meta.env.BASE_URL}${name}`;
