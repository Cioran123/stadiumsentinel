import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Loaded at runtime (not bundled) so Weave can patch the Anthropic client for tracing.
  serverExternalPackages: ["weave", "@anthropic-ai/sdk"],
};

export default nextConfig;
