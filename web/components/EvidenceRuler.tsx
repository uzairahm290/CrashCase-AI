"use client";

import { useState } from "react";
import type { Assessment } from "@/lib/api";
import { CAR_TEXT, label, money, moneyShort, ordinal, pct } from "@/lib/format";
import styles from "./EvidenceRuler.module.css";

// Drawn in a 480-wide coordinate space so text stays legible when the card is ~420px wide.
const W = 480;
const H = 104;
const PAD = 16;
const AXIS_Y = 74;

function niceTicks(lo: number, hi: number, count = 5) {
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

/**
 * The PKR scale for one damage: each dot is a similar past claim, placed at its price
 * transferred to this car (dot size = how visually similar it is). The yellow band is
 * the estimate range; the ink line is the estimate.
 */
export default function EvidenceRuler({ a }: { a: Assessment }) {
  const [hover, setHover] = useState<number | null>(null);
  const points = a.similar_claims.map((s) => s.adjusted_cost_pkr ?? s.cost_pkr);
  const all = [...points, a.cost_low_pkr, a.cost_high_pkr];
  const span = Math.max(...all) - Math.min(...all) || a.cost_estimate_pkr * 0.2;
  const lo = Math.max(0, Math.min(...all) - span * 0.15);
  const hi = Math.max(...all) + span * 0.15;
  const x = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - PAD * 2);

  if (a.basis === "cost_table") {
    return (
      <p className={styles.none}>
        No similar past claims for this damage yet, so it was priced from the parts and labour table. It
        will be priced from evidence once adjusters approve claims like it.
      </p>
    );
  }

  const active = hover != null ? a.similar_claims[hover] : null;

  return (
    <figure className={styles.fig}>
      <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} role="img" aria-label={`Estimate PKR ${money(a.cost_low_pkr)} to ${money(a.cost_high_pkr)}, based on ${a.similar_claims.length} similar past claims`}>
        <rect
          x={x(a.cost_low_pkr)}
          y={14}
          width={Math.max(2, x(a.cost_high_pkr) - x(a.cost_low_pkr))}
          height={AXIS_Y - 14}
          className={styles.band}
        />
        <line x1={x(a.cost_low_pkr)} x2={x(a.cost_low_pkr)} y1={14} y2={AXIS_Y} className={styles.edge} />
        <line x1={x(a.cost_high_pkr)} x2={x(a.cost_high_pkr)} y1={14} y2={AXIS_Y} className={styles.edge} />

        <line x1={PAD} x2={W - PAD} y1={AXIS_Y} y2={AXIS_Y} className={styles.axis} />
        {niceTicks(lo, hi).map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={AXIS_Y} y2={AXIS_Y + 5} className={styles.axis} />
            <text x={x(t)} y={AXIS_Y + 20} className={styles.tick}>
              {moneyShort(t)}
            </text>
          </g>
        ))}

        {a.similar_claims.map((s, i) => {
          const v = points[i];
          // Claims arrive closest-first; size by rank so the closest matches stand out.
          const r = Math.max(5, 10 - i * 1.2);
          const y = 30 + (i % 3) * 15;
          return (
            <circle
              key={s.claim_ref}
              cx={x(v)}
              cy={y}
              r={r}
              className={styles.dot}
              data-on={hover === i || undefined}
              tabIndex={0}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              <title>{`${s.claim_ref}: PKR ${money(v)}`}</title>
            </circle>
          );
        })}

        <line
          x1={x(a.cost_estimate_pkr)}
          x2={x(a.cost_estimate_pkr)}
          y1={8}
          y2={AXIS_Y}
          className={styles.estimate}
        />
      </svg>
      <figcaption className={styles.cap}>
        {active ? (
          <>
            <strong>{active.claim_ref}</strong>: {label(active.damage_type)} on {label(active.part)},{" "}
            {CAR_TEXT[active.car_category] ?? active.car_category}, {pct(active.severity)} of the part. Paid PKR{" "}
            {money(active.cost_pkr)}, which is PKR {money(active.adjusted_cost_pkr ?? active.cost_pkr)} for this car.
            The {ordinal(hover!)} visual match.
          </>
        ) : (
          <>
            Each dot is a similar past claim, priced for this car. Bigger dots look more like this damage. The
            yellow band is the estimate; hover a dot for details.
          </>
        )}
      </figcaption>
    </figure>
  );
}
