import type { Metadata } from "next";
import Rail from "@/components/Rail";
import "./globals.css";
import styles from "./layout.module.css";

export const metadata: Metadata = {
  title: "CrashCase AI",
  description: "Car damage claims assessed from photos, priced against similar past claims.",
  icons: { icon: "/icon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className={styles.shell}>
          <Rail />
          <main className={styles.main}>{children}</main>
        </div>
      </body>
    </html>
  );
}
