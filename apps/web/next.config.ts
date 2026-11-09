import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  experimental: { cpus: 2 },
  async rewrites() {
    const origin = process.env.NEXUS_API_ORIGIN;
    return origin
      ? [{ source: "/api/:path*", destination: `${origin.replace(/\/$/, "")}/api/:path*` }]
      : [];
  },
  webpack(config, { dev }) {
    // Production builds on this low-disk host avoid a large disposable filesystem cache.
    if (!dev) config.cache = false;
    return config;
  },
};
export default config;
