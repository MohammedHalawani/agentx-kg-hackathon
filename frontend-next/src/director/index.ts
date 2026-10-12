/**
 * Director mode: recording-only hooks for the staged showcase videos. It is on only when the
 * page was opened with `?director=1` (remembered for that browser tab), so the normal product
 * never runs this path and shows nothing of it. In director mode the case page accepts cues
 * from the recording script (select a record, show the phone visual); the script itself waits
 * on the backend's real stage events before sending each cue.
 */
function read(): boolean {
  if (typeof window === "undefined") return false;
  try {
    if (new URLSearchParams(window.location.search).has("director"))
      window.sessionStorage.setItem("suhail-director", "1");
    return window.sessionStorage.getItem("suhail-director") === "1";
  } catch {
    return false;
  }
}
export const DIRECTOR = read();
