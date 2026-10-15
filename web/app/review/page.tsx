"use client";

import Link from "next/link";
import ClaimTable from "@/components/ClaimTable";
import { useLoad } from "@/components/useLoad";
import { api } from "@/lib/api";

export default function ReviewPage() {
  const { data, error } = useLoad(() => api.listClaims("done"), [], 5000);
  const flagged = data?.filter((c) => c.fraud_flagged) ?? [];
  const ordered = data ? [...flagged, ...data.filter((c) => !c.fraud_flagged)] : null;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="muted">
            Claims with an estimate waiting for your decision. Claims flagged for possible fraud are listed first.
          </p>
        </div>
      </header>
      {error && <p className="error-box">{error}</p>}
      {ordered && ordered.length > 0 && <ClaimTable claims={ordered} />}
      {ordered && ordered.length === 0 && (
        <div className="panel" style={{ padding: "36px 28px", display: "grid", gap: 10, justifyItems: "start" }}>
          <h2>The queue is clear</h2>
          <p className="muted">New estimates show up here as soon as the photos are assessed.</p>
          <Link href="/" className="btn btn-quiet">
            See all claims
          </Link>
        </div>
      )}
    </div>
  );
}
