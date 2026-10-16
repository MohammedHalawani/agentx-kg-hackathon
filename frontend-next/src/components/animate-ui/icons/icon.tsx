// Local, deliberately limited adapter for the three vendored Animate UI icons.
// No in-view playback, looping or additional dependencies. See SOURCE.md.
import { useEffect, type ComponentType } from "react";
import {
  useAnimation,
  useReducedMotion,
  type SVGMotionProps,
} from "motion/react";

import { IconContext } from "./icon-context";

export type IconProps<T extends string> = Omit<
  SVGMotionProps<SVGSVGElement>,
  "animate"
> & {
  size?: number;
  animate?: boolean;
  animation?: T;
};
export function IconWrapper<T extends string>({
  icon: Icon,
  animate = false,
  animation,
  size = 18,
  ...props
}: IconProps<T> & { icon: ComponentType<IconProps<T>> }) {
  const controls = useAnimation();
  const reduce = useReducedMotion();
  useEffect(() => {
    if (animate && !reduce) void controls.start("animate");
    else controls.set("initial");
    return () => controls.stop();
  }, [animate, reduce, controls]);
  return (
    <IconContext.Provider
      value={{ controls, animation: animation ?? "default" }}
    >
      <Icon size={size} aria-hidden="true" {...props} />
    </IconContext.Provider>
  );
}
