import type { NextConfig } from "next";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");
const WS = API.replace(/^http/, "ws");
const prod = process.env.NODE_ENV === "production";

// Production only (the dev server needs eval for hot reload). The UI may talk to
// itself and to the configured backend - nothing else.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${API} ${WS}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The launcher builds into its own folder so it never collides with `npm run dev`.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // No secrets are ever exposed to the browser: only the public backend URL.
  env: { NEXT_PUBLIC_API_BASE: API },
  async headers() {
    const headers = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    ];
    if (prod) headers.push({ key: "Content-Security-Policy", value: csp });
    return [{ source: "/:path*", headers }];
  },
};

export default nextConfig;
