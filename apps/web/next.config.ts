import type { NextConfig } from "next";

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  experimental: { cpus: 2 },
  webpack(config, { dev }) {
    // Production builds on this low-disk host avoid a large disposable filesystem cache.
    if (!dev) config.cache = false;
    return config;
  },
};
export default config;
