import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output is only for self-hosted Docker builds; Vercel natively handles tracing
  ...(process.env.BUILD_STANDALONE === "true"
    ? {
        output: "standalone",
        outputFileTracingIncludes: {
          "/**": ["./node_modules/@swc/helpers/**/*"],
        },
      }
    : {}),
};

export default nextConfig;

