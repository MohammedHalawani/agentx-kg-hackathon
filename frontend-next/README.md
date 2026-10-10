# Suhail interface (frontend-next)

The redesigned Suhail operations interface: React 19, TypeScript, Vite, Tailwind CSS 4 and the
official shadcn/ui **Nova / Radix** preset. It started as the standalone UI lab
(`C:\Projects\suhail_ui`, copied verbatim in the first commit; hashes in
`SOURCE_MANIFEST.sha256`) and is now connected to the Suhail backend.

The backend serves the built app at **`/app/`**. The previous interface (`frontend/`) is
unchanged and still served at `/`.

## Connected app

```powershell
cd frontend-next
npm ci
npm run build
# start the backend, then open http://127.0.0.1:8000/app/
```

Every case, stage, decision and outcome on screen comes from the backend. The data is a
synthetic logistics dataset and is labelled as such; it is not SPL operational data.
See [INTEGRATION.md](INTEGRATION.md) for what is connected, the rules the app follows and the
gaps that still need backend work.

## UI lab (design and regression)

```powershell
npm run dev:lab        # http://127.0.0.1:5180/
```

The lab is the original browser-only build: fixture cases, a local timer and a scripted
assistant. It is for design work and for checking that the integrated code still looks and
behaves like the original lab. None of it is in the connected build. The lab's own notes are in
[VERIFICATION.md](VERIFICATION.md); the reference screenshots are in `screenshots/` (`final-*`
are the lab, `connected-*` are the connected app).

## Checks

```powershell
npm run typecheck
npm run lint
npm test               # unit: adapters, backend service, original lab units
npm run test:e2e       # connected app in Chrome against a scripted backend stand-in
npm run test:e2e:lab   # the original 20 lab browser tests on this codebase
```
