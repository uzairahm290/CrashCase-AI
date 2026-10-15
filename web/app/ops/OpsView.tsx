"use client";

import { useLoad } from "@/components/useLoad";
import { api } from "@/lib/api";
import { money, sentence, STATUS_TEXT } from "@/lib/format";
import type { ClaimStatus } from "@/lib/api";
import DriftPanel from "./DriftPanel";
import styles from "./ops.module.css";

type Link = { name: string; url: string; what: string };

const STATUS_ORDER: ClaimStatus[] = ["approved", "done", "declined", "rejected", "failed", "processing", "queued"];

export default function OpsView({ links }: { links: Link[] }) {
  const { data: s, error } = useLoad(() => api.stats(), [], 10000);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Operations</h1>
          <p className="muted">How the assessment service is running, refreshed every 10 seconds.</p>
        </div>
      </header>
      {error && <p className="error-box">{error}</p>}
      {s && (
        <div className={styles.grid}>
          <section className={`panel ${styles.facts}`}>
            <div>
              <p className="muted">Claims assessed</p>
              <p className={`figure ${styles.n}`}>{s.claims_total}</p>
            </div>
            <div>
              <p className="muted">Average assessment time</p>
              <p className={`figure ${styles.n}`}>
                {s.avg_pipeline_seconds != null ? `${s.avg_pipeline_seconds.toFixed(2)} s` : "—"}
              </p>
            </div>
            <div>
              <p className="muted">Past claims used for pricing</p>
              <p className={`figure ${styles.n}`}>{s.index_size.toLocaleString("en")}</p>
            </div>
            <div>
              <p className="muted">Approved payouts</p>
              <p className={`figure ${styles.n}`}>PKR {money(s.approved_value_pkr)}</p>
            </div>
          </section>

          <section className={`panel ${styles.block}`}>
            <h2>Claims by status</h2>
            {s.claims_total === 0 ? (
              <p className="muted">No claims yet.</p>
            ) : (
              <>
                <div className={styles.stack} role="img" aria-label="Share of claims in each status">
                  {STATUS_ORDER.filter((k) => s.by_status[k]).map((k) => (
                    <span
                      key={k}
                      className={styles[k]}
                      style={{ flexGrow: s.by_status[k] }}
                      title={`${STATUS_TEXT[k]}: ${s.by_status[k]}`}
                    />
                  ))}
                </div>
                <ul className={styles.legend}>
                  {STATUS_ORDER.filter((k) => s.by_status[k]).map((k) => (
                    <li key={k}>
                      <span className={`${styles.swatch} ${styles[k]}`} />
                      {STATUS_TEXT[k]} <strong>{s.by_status[k]}</strong>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p className={styles.fraudLine}>
              {s.fraud_flagged
                ? `${s.fraud_flagged} claim${s.fraud_flagged === 1 ? " was" : "s were"} flagged for possible fraud.`
                : "No claims flagged for fraud."}
            </p>
          </section>

          <section className={`panel ${styles.block}`}>
            <h2>Damage found</h2>
            {Object.keys(s.damage_mix).length === 0 ? (
              <p className="muted">No damage assessed yet.</p>
            ) : (
              <ul className={styles.bars}>
                {Object.entries(s.damage_mix)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => {
                    const max = Math.max(...Object.values(s.damage_mix));
                    return (
                      <li key={k}>
                        <span className={styles.barLabel}>{sentence(k)}</span>
                        <span className={styles.bar}>
                          <span style={{ width: `${(v / max) * 100}%` }} />
                        </span>
                        <span className={styles.barN}>{v}</span>
                      </li>
                    );
                  })}
              </ul>
            )}
          </section>

          <DriftPanel />

          <section className={`panel ${styles.block}`}>
            <h2>Models in production</h2>
            <dl className={styles.models}>
              <dt>Damage detection</dt>
              <dd>{s.model_versions.detector}</dd>
              <dt>Image matching</dt>
              <dd>{s.model_versions.embedder}</dd>
            </dl>
          </section>

          {links.length > 0 && (
            <section className={`panel ${styles.block}`}>
              <h2>Tools</h2>
              <ul className={styles.links}>
                {links.map((l) => (
                  <li key={l.name}>
                    <a href={l.url} target="_blank" rel="noreferrer">
                      {l.name}
                    </a>
                    <span className="muted">{l.what}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
