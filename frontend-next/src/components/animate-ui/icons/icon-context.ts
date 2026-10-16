import { createContext, useContext } from "react";
import type { useAnimation, Variants } from "motion/react";
export const IconContext = createContext<{
  controls: ReturnType<typeof useAnimation> | undefined;
  animation: string;
}>({ controls: undefined, animation: "default" });
export function useAnimateIconContext() {
  return useContext(IconContext);
}
export function getVariants<T extends Record<string, Record<string, Variants>>>(
  animations: T,
  animation: string,
): Record<string, Variants> {
  return animations[animation] ?? animations.default;
}
