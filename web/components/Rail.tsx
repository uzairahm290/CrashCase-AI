"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import styles from "./Rail.module.css";

const NAV = [
  { href: "/", text: "Claims" },
  { href: "/claims/new", text: "New claim" },
  { href: "/review", text: "Review queue", badge: true },
  { href: "/ops", text: "Operations" },
];

export function Mark({ size = 28 }: { size?: number }) {
  // Crop-mark corners around a dent: the photo inspector's viewfinder.
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 11V3h8M21 3h8v8M29 21v8h-8M11 29H3v-8" fill="none" stroke="#F2C230" strokeWidth="3" />
      <path d="M10 18c3-5 9-5 12 0" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export default function Rail() {
  const path = usePathname();
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    const load = () =>
      api
        .listClaims("done")
        .then((c) => live && setPending(c.length))
        .catch(() => live && setPending(null));
    load();
    const t = setInterval(load, 10000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [path]);

  const active = (href: string) =>
    href === "/" ? path === "/" || (path.startsWith("/claims/") && path !== "/claims/new") : path === href;

  return (
    <aside className={styles.rail}>
      <Link href="/" className={styles.brand}>
        <Mark />
        <span>
          CrashCase <span className={styles.ai}>AI</span>
        </span>
      </Link>
      <nav className={styles.nav} aria-label="Main">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className={styles.link}
            aria-current={active(n.href) ? "page" : undefined}
          >
            {n.text}
            {n.badge && pending ? <span className={styles.badge}>{pending}</span> : null}
          </Link>
        ))}
      </nav>
      <p className={styles.foot}>
        Estimates are drafts. An adjuster signs off every claim before payout.
      </p>
    </aside>
  );
}
