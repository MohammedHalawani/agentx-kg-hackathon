import { useEffect, useState } from "react";
import { Check, ScanLine } from "lucide-react";

/**
 * Recording only. A phone that slides in beside the case to VISUALISE the simulated request a
 * worker would receive: a notification, a short message with three options, the choice made in
 * the staged scenario, and a confirmation. It is a picture of a simulated logistics request,
 * not a messaging integration: nothing is sent to any device, and it changes no case record.
 * It exists only when the page runs in director mode and is driven by the recording script.
 */
export interface PhoneScript {
  /** 0 hidden, 1 notification, 2 message with options, 3 option pressed, 4 confirmation. */
  step: number;
  title: string;
  body: string;
  options: string[];
  chosen: number;
  confirmation: string;
}
const HIDDEN: PhoneScript = {
  step: 0,
  title: "",
  body: "",
  options: [],
  chosen: 0,
  confirmation: "",
};

export function PhoneOverlay() {
  const [script, setScript] = useState<PhoneScript>(HIDDEN);
  // Kept mounted through the slide-out, then removed.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const on = (event: Event) => {
      // A cue changes only what it names, so the screen keeps its content while sliding out.
      const next = (event as CustomEvent<Partial<PhoneScript>>).detail ?? {};
      setScript((current) => ({ ...current, ...next }));
      if ((next.step ?? 0) > 0) setMounted(true);
    };
    window.addEventListener("suhail:phone", on);
    return () => window.removeEventListener("suhail:phone", on);
  }, []);
  useEffect(() => {
    if (script.step > 0) return;
    const timer = setTimeout(() => setMounted(false), 700);
    return () => clearTimeout(timer);
  }, [script.step]);
  if (!mounted) return null;
  const now = new Date().toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <div
      className={`director-phone ${script.step > 0 ? "in" : "out"}`}
      aria-hidden="true"
    >
      <div className="phone-body">
        <div className="phone-island" />
        <div className="phone-screen">
          <div className="phone-status">
            <span>{now}</span>
            <span className="phone-signal">
              <i />
              <i />
              <i />
              <b />
            </span>
          </div>
          {script.step === 1 && (
            <div className="phone-lock">
              <div className="phone-clock">{now}</div>
              <div className="phone-notification">
                <img src={`${import.meta.env.BASE_URL}suhail.svg`} alt="" />
                <div>
                  <b>
                    Suhail <small>now</small>
                  </b>
                  <strong>{script.title}</strong>
                  <p>{script.body}</p>
                </div>
              </div>
            </div>
          )}
          {script.step >= 2 && (
            <div className="phone-app">
              <header>
                <img src={`${import.meta.env.BASE_URL}suhail.svg`} alt="" />
                <div>
                  <b>Suhail</b>
                  <small>{script.title}</small>
                </div>
              </header>
              <p className="phone-message">{script.body}</p>
              {script.step < 4 ? (
                <div className="phone-options">
                  {script.options.map((option, index) => (
                    <span
                      key={option}
                      className={
                        script.step === 3 && index === script.chosen
                          ? "pressed"
                          : ""
                      }
                    >
                      {script.step === 3 && index === script.chosen && (
                        <ScanLine size={15} />
                      )}
                      {option}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="phone-confirmed">
                  <span>
                    <Check size={26} />
                  </span>
                  <b>{script.confirmation}</b>
                </div>
              )}
            </div>
          )}
          <div className="phone-home" />
        </div>
      </div>
    </div>
  );
}
