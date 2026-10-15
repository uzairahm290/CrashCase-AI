"use client";

import Link from "next/link";
import { useState } from "react";
import ClaimTable from "@/components/ClaimTable";
import { useLoad } from "@/components/useLoad";
import { api, type ClaimStatus } from "@/lib/api";
import styles from "./claims.module.css";

const FILTERS: { value: ClaimStatus | undefined; text: string }[] = [
  { value: undefined, text: "All" },
  { value: "done", text: "Needs review" },
  { value: "approved", text: "Approved" },
  { value: "declined", text: "Declined" },
  { value: "rejected", text: "Photos rejected" },
];

export default function ClaimsPage() {
  const [filter, setFilter] = useState<ClaimStatus | undefined>(undefined);
  const { data, error } = useLoad(() => api.listClaims(filter), [filter], 5000);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Claims</h1>
          <p className="muted">Every submitted claim, newest first. Open one to see the evidence behind its price.</p>
        </div>
        <Link href="/claims/new" className="btn btn-marker">
          Start a claim
        </Link>
      </header>

      <div className={styles.filters} role="tablist" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.text}
            role="tab"
            aria-selected={filter === f.value}
            className={styles.filter}
            onClick={() => setFilter(f.value)}
          >
            {f.text}
          </button>
        ))}
      </div>

      {error && <p className="error-box">{error}</p>}
      {data && data.length > 0 && <ClaimTable claims={data} />}
      {data && data.length === 0 && (
        <div className={`panel ${styles.empty}`}>
          <h2>{filter ? "Nothing here yet" : "No claims yet"}</h2>
          <p className="muted">
            {filter
              ? "No claims have this status right now."
              : "Upload a few photos of a damaged car to get an itemised estimate in seconds."}
          </p>
          {!filter && (
            <Link href="/claims/new" className="btn">
              Start a claim
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
