"use client";
/* Carga: una silueta del contenido que llegará, nunca una ruleta en medio. */

export default function Skeleton({
  width = "100%",
  height = 16,
  count = 1,
}: {
  width?: number | string;
  height?: number | string;
  count?: number;
}) {
  const rows = Array.from({ length: count });
  return (
    <span aria-hidden="true" style={{ display: "grid", gap: 6 }}>
      {rows.map((_, i) => (
        <span
          key={i}
          className="skeleton"
          style={{
            display: "block",
            width: typeof width === "number" ? `${width}px` : width,
            height: typeof height === "number" ? `${height}px` : height,
          }}
        />
      ))}
    </span>
  );
}
