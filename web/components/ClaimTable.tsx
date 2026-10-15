"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type ClaimSummary } from "@/lib/api";
import { CAR_TEXT, money, shortId, when } from "@/lib/format";
import StatusPill from "./StatusPill";
import styles from "./ClaimTable.module.css";

export default function ClaimTable({ claims }: { claims: ClaimSummary[] }) {
  const router = useRouter();
  return (
    <div className={`panel ${styles.wrap}`}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Claim</th>
            <th scope="col">Car</th>
            <th scope="col" className={styles.num}>
              Damage
            </th>
            <th scope="col" className={styles.num}>
              Estimate (PKR)
            </th>
            <th scope="col">Status</th>
            <th scope="col">Submitted</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((c) => (
            <tr key={c.claim_id} onClick={() => router.push(`/claims/${c.claim_id}`)}>
              <td>
                <div className={styles.claim}>
                  {c.images[0] ? (
                    <img src={api.imageUrl(c.claim_id, c.images[0])} alt="" className={styles.thumb} />
                  ) : (
                    <span className={styles.thumb} />
                  )}
                  <span>
                    <Link href={`/claims/${c.claim_id}`} className={styles.id}>
                      {shortId(c.claim_id)}
                    </Link>
                    <span className={styles.sub}>
                      {c.images.length} photo{c.images.length === 1 ? "" : "s"}
                      {c.fraud_flagged && <span className={styles.flag}>Possible fraud</span>}
                    </span>
                  </span>
                </div>
              </td>
              <td>{CAR_TEXT[c.car_category]}</td>
              <td className={styles.num}>{c.damage_count || "—"}</td>
              <td className={styles.num}>
                {c.final_cost_pkr != null ? (
                  <strong>{money(c.final_cost_pkr)}</strong>
                ) : c.total_low_pkr != null && c.total_high_pkr ? (
                  <>
                    {money(c.total_low_pkr)}
                    <span className="muted"> – </span>
                    {money(c.total_high_pkr)}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                <StatusPill status={c.status} />
              </td>
              <td className="muted">{when(c.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
