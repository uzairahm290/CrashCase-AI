"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import EvidenceRuler from "@/components/EvidenceRuler";
import PhotoStage from "@/components/PhotoStage";
import StatusPill from "@/components/StatusPill";
import { useLoad } from "@/components/useLoad";
import { api, type Claim } from "@/lib/api";
import { CAR_TEXT, label, money, pct, sentence, shortId, when } from "@/lib/format";
import styles from "./claim.module.css";

const STEPS = ["Checking photo quality", "Finding damage", "Matching past claims", "Pricing", "Writing the report"];

function Assessing({ status }: { status: string }) {
  // The worker doesn't report stage progress, so advance through the steps on a timer
  // purely as a sign of life; the page switches to the result the moment it lands.
  const [step, setStep] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 700);
    return () => clearInterval(t);
  }, []);
  return (
    <div className={`panel ${styles.assessing}`} aria-live="polite">
      <h2>{status === "queued" ? "Waiting for an assessor" : "Assessing the photos"}</h2>
      <ol className={styles.steps}>
        {STEPS.map((s, i) => (
          <li key={s} data-state={i < step ? "done" : i === step ? "now" : "later"}>
            {s}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Decision({ claim, onDone }: { claim: Claim; onDone: (c: Claim) => void }) {
  const r = claim.result!;
  const mid = Math.round((r.total_low_pkr + r.total_high_pkr) / 2 / 100) * 100;
  const [amount, setAmount] = useState(mid.toLocaleString("en"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const value = Number(amount.replace(/,/g, ""));
  const outside = value > 0 && (value < r.total_low_pkr * 0.8 || value > r.total_high_pkr * 1.2);

  async function decide(approved: boolean) {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.review(claim.claim_id, approved, approved ? value : undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The decision was not saved.");
      setBusy(false);
    }
  }

  return (
    <section className={`panel ${styles.decision}`} aria-labelledby="decide-h">
      <h2 id="decide-h">Your decision</h2>
      <label className={styles.amount}>
        <span>Amount to pay (PKR)</span>
        <input
          inputMode="numeric"
          value={amount}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, "");
            setAmount(digits ? Number(digits).toLocaleString("en") : "");
          }}
        />
      </label>
      {outside && (
        <p className={styles.warn}>
          This is well outside the estimate. Add a note to the file explaining why before approving.
        </p>
      )}
      {error && <p className="error-box">{error}</p>}
      <div className={styles.actions}>
        <button className="btn" disabled={busy || !(value > 0)} onClick={() => decide(true)}>
          Approve PKR {value > 0 ? money(value) : "—"}
        </button>
        <button className="btn btn-quiet" disabled={busy} onClick={() => decide(false)}>
          Decline
        </button>
      </div>
      <p className="muted">Approved claims become evidence for pricing future claims.</p>
    </section>
  );
}

export default function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [poll, setPoll] = useState(true);
  const { data: claim, error, setData } = useLoad(() => api.getClaim(id), [id], poll ? 1500 : undefined);
  const [current, setCurrent] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (claim && !["queued", "processing"].includes(claim.status)) setPoll(false);
  }, [claim]);

  if (error && !claim) {
    return (
      <div className="page">
        <p className="error-box">{error}</p>
      </div>
    );
  }
  if (!claim) return <div className="page muted">Loading claim…</div>;

  const r = claim.result;
  const image = current ?? claim.images[0];

  function select(n: number | null) {
    setSelected(n);
    if (n != null && r) setCurrent(r.assessments[n].image);
  }

  return (
    <div className={`page ${styles.page}`}>
      <header className={styles.head}>
        <div>
          <p className={styles.crumb}>
            <Link href="/">Claims</Link> / {shortId(claim.claim_id)}
          </p>
          <h1>
            {CAR_TEXT[claim.car_category]},{" "}
            {claim.images.length} photo{claim.images.length === 1 ? "" : "s"}
          </h1>
          <p className="muted">Submitted {when(claim.created_at)}</p>
        </div>
        <StatusPill status={claim.status} />
      </header>

      {r?.fraud.flagged && (
        <div className={styles.fraud} role="alert">
          <strong>Check this claim before paying.</strong>
          <ul>
            {r.fraud.reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}

      {claim.status === "failed" && <p className="error-box">The assessment failed: {claim.error}</p>}

      <div className={styles.grid}>
        <div className={styles.left}>
          <PhotoStage
            claimId={claim.claim_id}
            images={claim.images}
            assessments={r?.assessments ?? []}
            quality={r?.quality ?? []}
            current={image}
            onPick={(n) => {
              setCurrent(n);
              setSelected(null);
            }}
            selected={selected}
            onSelect={select}
          />

          {r && (
            <section className={`panel ${styles.report}`} aria-labelledby="report-h">
              <div className={styles.reportHead}>
                <h2 id="report-h">Claim report</h2>
                <span className="muted">
                  {r.model_versions.report === "template" ? "Standard template" : "Written by the assistant"}
                </span>
              </div>
              <div className={styles.reportBody}>{r.report}</div>
            </section>
          )}
        </div>

        <div className={styles.right}>
          {!r && <Assessing status={claim.status} />}

          {r && (
            <>
              <section className={`panel ${styles.total}`}>
                <p className="muted">
                  {claim.final_cost_pkr != null ? "Approved amount" : "Estimated repair cost"}
                </p>
                {claim.final_cost_pkr != null ? (
                  <p className={`figure ${styles.big}`}>PKR {money(claim.final_cost_pkr)}</p>
                ) : r.assessments.length ? (
                  <p className={`figure ${styles.big}`}>
                    {money(r.total_low_pkr)}
                    <span className={styles.to}>to</span>
                    {money(r.total_high_pkr)}
                  </p>
                ) : (
                  <p className={styles.bigNone}>No damage found</p>
                )}
                {r.assessments.length > 0 && claim.final_cost_pkr == null && (
                  <p className="muted">
                    PKR, across {r.assessments.length} damaged area{r.assessments.length === 1 ? "" : "s"}
                  </p>
                )}
              </section>

              {claim.status === "rejected" && (
                <div className="error-box">
                  None of the photos could be assessed. Ask the customer to retake them in daylight, holding
                  the phone steady.
                </div>
              )}

              <ol className={styles.jobs} aria-label="Damage found">
                {r.assessments.map((a, i) => (
                  <li
                    key={i}
                    className={`panel ${styles.job}`}
                    data-on={selected === i || undefined}
                    onMouseEnter={() => a.image === image && setSelected(i)}
                    onMouseLeave={() => setSelected(null)}
                  >
                    <button type="button" className={styles.jobHead} onClick={() => select(i)}>
                      <span className={styles.jobNum}>{i + 1}</span>
                      <span className={styles.jobTitle}>
                        <strong>
                          {sentence(a.detection.damage_type)} on{" "}
                          {label(a.detection.part)}
                        </strong>
                        <span className="muted">
                          {pct(a.detection.severity)} of the part, {a.action}
                        </span>
                      </span>
                      <span className={styles.jobCost}>
                        {money(a.cost_low_pkr)}–{money(a.cost_high_pkr)}
                      </span>
                    </button>
                    <div className={styles.sev} aria-hidden="true">
                      <span style={{ width: pct(a.detection.severity) }} />
                    </div>
                    <EvidenceRuler a={a} />
                  </li>
                ))}
              </ol>

              {claim.status === "done" && <Decision claim={claim} onDone={setData} />}
              {(claim.status === "approved" || claim.status === "declined") && (
                <p className={styles.decided}>
                  {claim.status === "approved"
                    ? "Approved. This claim now helps price similar damage."
                    : "Declined. Nothing was added to the pricing evidence."}
                </p>
              )}

              <details className={styles.how}>
                <summary>How this was assessed</summary>
                <dl>
                  <dt>Damage model</dt>
                  <dd>{r.model_versions.detector}</dd>
                  <dt>Image matching</dt>
                  <dd>{r.model_versions.embedder}</dd>
                  <dt>Report</dt>
                  <dd>
                    {r.model_versions.report}, prompt {r.prompt_version}
                  </dd>
                  <dt>Time taken</dt>
                  <dd>{r.pipeline_seconds.toFixed(2)} s</dd>
                </dl>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
