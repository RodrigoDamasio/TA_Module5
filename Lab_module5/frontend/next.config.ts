import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray package-lock.json in the home folder would otherwise be taken as the root.
  turbopack: { root: path.join(__dirname) },
};

export default nextConfig;
