const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return process.env.BACKEND_URL
      ? [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }]
      : [];
  },
};

export default nextConfig;
