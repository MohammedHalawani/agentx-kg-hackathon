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
export function dateTimeLabel(timestamp: string) {
  return `${dateLabel(timestamp)} · ${timeLabel(timestamp)} AST`;
}
