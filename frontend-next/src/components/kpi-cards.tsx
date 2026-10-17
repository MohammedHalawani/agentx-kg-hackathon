import type { ReactNode } from "react";

export interface KpiCard {
  key: string;
  icon: ReactNode;
  value: number | null;
  label: string;
  /** What the number counts, exactly; shown as the card's tooltip. */
  title: string;
  /** Applies a visible, reversible filter when the card is clicked. */
  onSelect?: () => void;
  active?: boolean;
}

/**
 * A short row of KPI cards: an icon, the number and a label. A null value is shown as a dash
 * (not loaded), never as zero. Cards with a filter are buttons; the others are plain figures.
 */
export function KpiCards({
  cards,
  label,
  testId,
}: {
  cards: KpiCard[];
  label: string;
  testId: string;
}) {
  return (
    <section className="kpi-row" aria-label={label} data-testid={testId}>
      {cards.map((card) => {
        const body = (
          <>
            <span className="kpi-icon" aria-hidden="true">
              {card.icon}
            </span>
            <b className="kpi-value" data-testid={`kpi-${card.key}`}>
              {card.value ?? "–"}
            </b>
            <span className="kpi-label">{card.label}</span>
          </>
        );
        return card.onSelect ? (
          <button
            key={card.key}
            type="button"
            className={`kpi-card ${card.active ? "active" : ""}`}
            title={card.title}
            aria-pressed={!!card.active}
            onClick={card.onSelect}
          >
            {body}
          </button>
        ) : (
          <div key={card.key} className="kpi-card" title={card.title}>
            {body}
          </div>
        );
      })}
    </section>
  );
}
