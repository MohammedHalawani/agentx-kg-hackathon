export function timeLabel(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("en-GB", {
    timeZone: "Asia/Riyadh",
    hour: "2-digit",
    minute: "2-digit",
  });
}
export function dateLabel(timestamp: string) {
  return new Date(timestamp).toLocaleDateString("en-GB", {
    timeZone: "Asia/Riyadh",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}
/** A measured duration in seconds as "41s" or "2m 05s". */
export function secondsLabel(seconds: number) {
  const whole = Math.max(0, Math.round(seconds));
  return whole < 60
    ? `${whole}s`
    : `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, "0")}s`;
}
export function dateTimeLabel(timestamp: string) {
  return `${dateLabel(timestamp)} · ${timeLabel(timestamp)} AST`;
}
