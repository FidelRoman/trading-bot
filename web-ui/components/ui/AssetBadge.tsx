"use client";

import React from "react";
import { getAssetBadgeInfo, formatPriceByAsset } from "@/lib/instruments";

interface AssetBadgeProps {
  symbol?: string | null;
  assetClass?: string | null;
  price?: number | null;
  digits?: number;
  showType?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export default function AssetBadge({
  symbol,
  assetClass,
  price,
  digits,
  showType = true,
  size = "md",
  className = "",
}: AssetBadgeProps) {
  const info = getAssetBadgeInfo(symbol, assetClass);
  const sym = symbol ?? "—";

  const sizeStyles = {
    sm: {
      padding: "1px 6px",
      fontSize: "var(--fs-eje)",
      gap: "var(--s-1)",
    },
    md: {
      padding: "2px 8px",
      fontSize: "var(--fs-xs)",
      gap: "var(--s-2)",
    },
    lg: {
      padding: "4px 12px",
      fontSize: "var(--fs-sm)",
      gap: "var(--s-3)",
    },
  }[size];

  return (
    <span
      className={`asset-badge ${info.category} ${className}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        border: "1px solid var(--rule-strong)",
        background: "var(--panel-inset)",
        color: "var(--ink)",
        fontVariantNumeric: "tabular-nums slashed-zero",
        ...sizeStyles,
      }}
    >
      <span
        style={{
          fontSize: "var(--fs-eje)",
          fontWeight: 700,
          letterSpacing: "0.06em",
          padding: "1px 4px",
          background:
            info.category === "forex"
              ? "var(--accent-wash)"
              : info.category === "share"
              ? "rgba(134, 70, 240, 0.14)"
              : info.category.startsWith("cfd_")
              ? "var(--warn-wash)"
              : "var(--long-wash)",
          color:
            info.category === "forex"
              ? "var(--accent)"
              : info.category === "share"
              ? "#8a45e6"
              : info.category.startsWith("cfd_")
              ? "var(--warn)"
              : "var(--long)",
          border: "1px solid var(--rule-faint)",
          textTransform: "uppercase",
        }}
      >
        {info.tag}
      </span>
      <span style={{ fontWeight: 700, letterSpacing: "-0.01em" }}>{sym}</span>
      {showType && (
        <span
          style={{
            color: "var(--ink-3)",
            fontSize: "var(--fs-eje)",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          · {info.label}
        </span>
      )}
      {price != null && (
        <span
          className="num"
          style={{
            fontWeight: 600,
            marginLeft: "var(--s-1)",
            color: "var(--ink-2)",
          }}
        >
          {formatPriceByAsset(price, symbol, assetClass, digits)}
        </span>
      )}
    </span>
  );
}
