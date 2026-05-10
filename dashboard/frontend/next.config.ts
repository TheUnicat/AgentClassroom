import type { NextConfig } from "next";

const config: NextConfig = {
  // Cloudflare Pages prefers static export; backend lives elsewhere on HF Spaces.
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default config;
