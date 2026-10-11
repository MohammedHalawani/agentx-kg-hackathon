import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

/** Backend routes the connected app calls. In development they are proxied to the backend. */
const API_ROUTES = [
  "/operations",
  "/cases",
  "/audit",
  "/explore",
  "/decisions",
  "/schema",
  "/graph",
  "/worker",
  "/shipments",
  "/simulation",
];

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, import.meta.dirname, ""), ...process.env };
  const lab = mode === "lab" || env.VITE_SUHAIL_DATA === "lab";
  const backend = env.SUHAIL_BACKEND ?? "http://127.0.0.1:8000";
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: [
        // Lab builds swap in the fixture lab; the connected build keeps the empty entry.
        ...(lab
          ? [
              {
                find: "@/services/lab-entry",
                replacement: path.resolve(
                  import.meta.dirname,
                  "./src/services/lab.ts",
                ),
              },
            ]
          : []),
        { find: "@", replacement: path.resolve(import.meta.dirname, "./src") },
      ],
    },
    // Connected product: served by the backend under /app/, so its routes never collide with
    // the API (/audit, /explore, /decisions, /cases/...). Lab: the standalone root.
    base: lab ? "/" : "/app/",
    define: lab
      ? { "import.meta.env.VITE_SUHAIL_DATA": JSON.stringify("lab") }
      : { "import.meta.env.VITE_SUHAIL_DATA": JSON.stringify("backend") },
    build: { outDir: lab ? "dist-lab" : "dist" },
    server: {
      host: "127.0.0.1",
      port: lab ? 5180 : 5190,
      strictPort: true,
      // SUHAIL_BACKEND=<origin> points the dev build at any running backend. Reads, operator
      // requests and the live stream all go through this proxy (the browser stays same-origin
      // with the dev server, which the backend's local-operations check accepts).
      proxy: lab
        ? undefined
        : Object.fromEntries(
            API_ROUTES.map((route) => [route, { target: backend }]),
          ),
    },
  };
});
