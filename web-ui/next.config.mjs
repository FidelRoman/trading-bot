/* Dos modos excluyentes: Next no admite `rewrites` junto a `output: "export"`.
 *
 * - Producción (`npm run build`, NEXT_EXPORT=1): export estático a `out/`, que
 *   sirve FastAPI. UI, /api y /ws comparten origen, así que no hace falta proxy.
 * - Desarrollo (`npm run dev`): Next sirve en :3000 y reescribe /api hacia el
 *   backend, que por defecto está en :8000.
 */
const BACKEND = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig =
  process.env.NEXT_EXPORT === "1"
    ? { output: "export", trailingSlash: true, images: { unoptimized: true } }
    : {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
        },
      };

export default nextConfig;
