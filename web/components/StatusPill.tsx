import type { ClaimStatus } from "@/lib/api";
import { STATUS_TEXT } from "@/lib/format";
import styles from "./StatusPill.module.css";

export default function StatusPill({ status }: { status: ClaimStatus }) {
  return (
    <span className={`${styles.pill} ${styles[status]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {STATUS_TEXT[status]}
    </span>
  );
}
