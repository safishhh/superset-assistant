import type { CSSProperties } from "react";
import { theme, type SupersetTheme } from "@apache-superset/core";

function asColor(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}

export function assistantThemeVars(tokens: SupersetTheme): CSSProperties {
  const radius = Number(tokens.borderRadiusLG ?? tokens.borderRadius ?? 12);
  return {
    "--sa-bg": asColor(
      tokens.colorBgElevated,
      asColor(tokens.colorBgContainer, "#ffffff"),
    ),
    "--sa-bg-container": asColor(tokens.colorBgContainer, "#ffffff"),
    "--sa-bg-soft": asColor(
      tokens.colorFillAlter,
      asColor(tokens.colorFillTertiary, "#f8fafc"),
    ),
    "--sa-bg-hover": asColor(
      tokens.colorFillSecondary,
      asColor(tokens.colorFillTertiary, "#f1f5f9"),
    ),
    "--sa-fg": asColor(tokens.colorText, "#0f172a"),
    "--sa-fg-soft": asColor(tokens.colorTextSecondary, "#475569"),
    "--sa-fg-muted": asColor(
      tokens.colorTextTertiary,
      asColor(tokens.colorTextSecondary, "#64748b"),
    ),
    "--sa-border": asColor(
      tokens.colorBorderSecondary,
      asColor(tokens.colorBorder, "#e2e8f0"),
    ),
    "--sa-border-strong": asColor(tokens.colorBorder, "#cbd5e1"),
    "--sa-accent": asColor(tokens.colorPrimary, "#2563eb"),
    "--sa-accent-soft": asColor(
      tokens.colorPrimaryBg,
      asColor(tokens.colorFillAlter, "#dbeafe"),
    ),
    "--sa-primary-border": asColor(
      tokens.colorPrimaryBorder,
      asColor(tokens.colorPrimary, "#2563eb"),
    ),
    "--sa-on-accent": asColor(tokens.colorTextLightSolid, "#ffffff"),
    "--sa-danger": asColor(tokens.colorError, "#dc2626"),
    "--sa-danger-soft": asColor(tokens.colorErrorBg, "#fee2e2"),
    "--sa-success": asColor(tokens.colorSuccess, "#16a34a"),
    "--sa-success-soft": asColor(tokens.colorSuccessBg, "#dcfce7"),
    "--sa-warn": asColor(tokens.colorWarning, "#b45309"),
    "--sa-warn-soft": asColor(tokens.colorWarningBg, "#fef3c7"),
    "--sa-radius": `${Math.max(8, radius)}px`,
    "--sa-radius-lg": `${Math.max(12, radius + 2)}px`,
    "--sa-radius-panel": `${Math.max(16, radius + 4)}px`,
    "--sa-shadow": asColor(
      tokens.boxShadowSecondary,
      "0 18px 48px rgba(15, 23, 42, 0.16)",
    ),
    "--sa-font": asColor(
      tokens.fontFamily,
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    ),
  } as CSSProperties;
}

export function useAssistantTheme(): CSSProperties {
  return assistantThemeVars(theme.useTheme());
}
