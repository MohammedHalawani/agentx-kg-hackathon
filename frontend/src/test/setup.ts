// jsdom doesn't implement matchMedia; motion's useReducedMotion (used across the chat components)
// needs it, so stub a non-reduced-motion default for component tests.
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// Node 22+ defines a global `localStorage` of its own that is unavailable unless the runtime
// was started with --localstorage-file, and it shadows the jsdom one for bare (unqualified)
// `localStorage` references in tests. Bind the global name to jsdom's working implementation
// so `localStorage.setItem(...)` in a test reaches the same storage the components read.
if (typeof window !== 'undefined') {
  const storage =
    window.localStorage ??
    (() => {
      const map = new Map<string, string>()
      return {
        getItem: (k: string) => map.get(k) ?? null,
        setItem: (k: string, v: string) => void map.set(k, String(v)),
        removeItem: (k: string) => void map.delete(k),
        clear: () => map.clear(),
        key: (i: number) => [...map.keys()][i] ?? null,
        get length() {
          return map.size
        },
      } as Storage
    })()
  Object.defineProperty(globalThis, 'localStorage', {
    value: storage,
    configurable: true,
    writable: true,
  })
}
