"use client";

import { useState } from "react";
import { useLoad } from "@/components/useLoad";
import { api } from "@/lib/api";
import { when } from "@/lib/format";
import styles from "./ops.module.css";

const COLUMN_TEXT: Record<string, string> = {
  brightness: "photo brightness",
  blur_score: "photo sharpness",
  severity: "damage severity",
  confidence: "model confidence",
  cost_estimate_pkr: "estimated cost",
  damage_type: "mix of damage types",
  part: "mix of damaged parts",
};

export default function DriftPanel() {
  const { data: d, error, setData } = useLoad(() => api.drift(), [], 60000);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setRunError(null);
    try {
      setData(await api.runDrift());
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "The check did not run.");
    } finally {
      setRunning(false);
    }
  }

  const changed = d?.drifted_columns.map((c) => COLUMN_TEXT[c] ?? c) ?? [];

  return (
    <section className={`panel ${styles.block} ${styles.wide}`}>
      <div className={styles.blockHead}>
        <h2>Are new claims like the old ones?</h2>
        <button className="btn btn-quiet" onClick={run} disabled={running}>
          {running ? "Checking…" : "Check now"}
        </button>
      </div>
      {error && <p className="error-box">{error}</p>}
      {runError && <p className="error-box">{runError}</p>}
      {d === null && <p className="muted">No check has run yet. It runs every day, or check now.</p>}
      {d && d.status === "not_enough_data" && (
        <p className="muted">
          Not enough claims to compare yet: {d.n_reference} earlier and {d.n_current} recent damaged areas,
          and each side needs {d.summary.needed ?? 20}. Checked {when(d.created_at)}.
        </p>
      )}
      {d && d.status !== "not_enough_data" && (
        <div className={styles.drift} data-state={d.status}>
          <p className={styles.driftHead}>
            {d.status === "drift"
              ? "Recent claims look different. Review the model before trusting new estimates."
              : changed.length
                ? "Mostly the same, with small shifts."
                : "Recent claims match the earlier ones."}
          </p>
          {changed.length > 0 && <p>Changed: {changed.join(", ")}.</p>}
          <p className="muted">
            Compared {d.n_current} recent damaged areas with {d.n_reference} earlier ones, {when(d.created_at)}.
          </p>
          {d.has_report && (
            <p className={styles.reportLinks}>
              <a href={api.driftReportUrl(d.id, "damage")} target="_blank" rel="noreferrer">
                Damage report
              </a>
              <a href={api.driftReportUrl(d.id, "photos")} target="_blank" rel="noreferrer">
                Photo report
              </a>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
