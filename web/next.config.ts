import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Photos are proxied through /api and already sized by the browser.
  images: { unoptimized: true },
};

export default config;
