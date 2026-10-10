import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray package-lock.json in the home folder would otherwise be taken as the root.
  turbopack: { root: path.join(__dirname) },
  // The build type-checks the app only: the tests import fixtures from ../backend, which is not
  // uploaded to Vercel. `npm run typecheck` still checks everything.
  typescript: { tsconfigPath: "tsconfig.build.json" },
};

export default nextConfig;
