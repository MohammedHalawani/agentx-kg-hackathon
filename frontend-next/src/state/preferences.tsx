import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { MotionConfig } from "motion/react";
import { DirectionProvider } from "@/components/ui/direction";
export type Preferences = {
  theme: "light" | "dark";
  language: "en" | "ar";
  motion: "system" | "reduce";
  density: "comfortable" | "compact";
};
const defaults: Preferences = {
  theme: "light",
  language: "en",
  motion: "system",
  density: "comfortable",
};
const Context = createContext<{
  preferences: Preferences;
  update: (change: Partial<Preferences>) => void;
  t: (english: string, arabic: string) => string;
} | null>(null);
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, set] = useState<Preferences>(() => {
    try {
      return {
        ...defaults,
        ...JSON.parse(
          localStorage.getItem("suhail-ui-lab.preferences") ?? "{}",
        ),
      };
    } catch {
      return defaults;
    }
  });
  useEffect(() => {
    document.documentElement.classList.toggle(
      "dark",
      preferences.theme === "dark",
    );
    document.documentElement.lang = preferences.language;
    document.documentElement.dir =
      preferences.language === "ar" ? "rtl" : "ltr";
    document.documentElement.dataset.motion = preferences.motion;
    document.documentElement.dataset.density = preferences.density;
    try {
      localStorage.setItem(
        "suhail-ui-lab.preferences",
        JSON.stringify(preferences),
      );
    } catch {
      /* Keep preferences in memory. */
    }
  }, [preferences]);
  return (
    <Context.Provider
      value={{
        preferences,
        update: (change) => set((p) => ({ ...p, ...change })),
        t: (en, ar) => (preferences.language === "ar" ? ar : en),
      }}
    >
      <DirectionProvider dir={preferences.language === "ar" ? "rtl" : "ltr"}>
        <MotionConfig
          reducedMotion={preferences.motion === "reduce" ? "always" : "user"}
          transition={{
            duration: preferences.motion === "reduce" ? 0 : 0.18,
            ease: [0.2, 0.7, 0.3, 1],
          }}
        >
          {children}
        </MotionConfig>
      </DirectionProvider>
    </Context.Provider>
  );
}
export function usePreferences() {
  const value = useContext(Context);
  if (!value) throw new Error("PreferencesProvider missing");
  return value;
}
