import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ConfigProvider, theme as antdTheme } from "antd";
import type { ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";

export type ThemeMode = "auto" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "sa-admin-theme";
const FONT =
  'Inter, Helvetica, Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';

type AdminThemeContextValue = {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
};

const AdminThemeContext = createContext<AdminThemeContextValue | null>(null);

function readMode(): ThemeMode {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "auto") {
      return value;
    }
  } catch {
    // Local storage may be unavailable.
  }
  return "auto";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function palette(resolved: ResolvedTheme) {
  if (resolved === "dark") {
    return {
      layout: "#141414",
      container: "#1f1f1f",
      elevated: "#1f1f1f",
      border: "#3a3a3a",
      borderSoft: "#303030",
      text: "rgba(255,255,255,0.85)",
      textSecondary: "rgba(255,255,255,0.65)",
      textTertiary: "rgba(255,255,255,0.45)",
      fillAlter: "rgba(255,255,255,0.04)",
      fillTertiary: "rgba(255,255,255,0.06)",
      fillSecondary: "rgba(255,255,255,0.12)",
      primaryBg: "#1a3a44",
      primaryBorder: "#2f6f7f",
      tableHeader: "#262626",
      rowHover: "#262626",
      segmented: "#343434",
    };
  }
  return {
    layout: "#f5f7fa",
    container: "#ffffff",
    elevated: "#ffffff",
    border: "#e8eaed",
    borderSoft: "#f0f0f0",
    text: "rgba(0,0,0,0.88)",
    textSecondary: "rgba(0,0,0,0.65)",
    textTertiary: "rgba(0,0,0,0.45)",
    fillAlter: "rgba(0,0,0,0.02)",
    fillTertiary: "rgba(0,0,0,0.04)",
    fillSecondary: "rgba(0,0,0,0.06)",
    primaryBg: "#e4f1f2",
    primaryBorder: "#98d0d9",
    tableHeader: "#fafafa",
    rowHover: "#f7fafb",
    segmented: "#ffffff",
  };
}

function themeConfig(resolved: ResolvedTheme): ThemeConfig {
  const colors = palette(resolved);
  return {
    algorithm:
      resolved === "dark" ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      fontFamily: FONT,
      fontSize: 14,
      fontSizeSM: 13,
      fontSizeLG: 16,
      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 6,
      colorPrimary: "#2893B3",
      colorInfo: "#2893B3",
      colorLink: "#2893B3",
      colorBgLayout: colors.layout,
      colorBgContainer: colors.container,
      colorBgElevated: colors.elevated,
      colorBorder: colors.border,
      colorBorderSecondary: colors.borderSoft,
      colorText: colors.text,
      colorTextSecondary: colors.textSecondary,
      colorTextTertiary: colors.textTertiary,
      colorFillAlter: colors.fillAlter,
      colorFillTertiary: colors.fillTertiary,
      colorFillSecondary: colors.fillSecondary,
      colorPrimaryBg: colors.primaryBg,
      colorPrimaryBorder: colors.primaryBorder,
      controlHeight: 32,
      controlHeightSM: 26,
    },
    components: {
      Layout: {
        headerBg: colors.container,
        siderBg: colors.container,
        bodyBg: colors.layout,
      },
      Menu: {
        itemBg: "transparent",
        itemColor: colors.textSecondary,
        itemHoverColor: colors.text,
        itemHoverBg: colors.fillTertiary,
        itemSelectedBg: colors.primaryBg,
        itemSelectedColor: "#2893B3",
        itemBorderRadius: 8,
        itemHeight: 36,
        itemMarginInline: 8,
        itemPaddingInline: 10,
        subMenuItemBg: "transparent",
      },
      Card: {
        headerBg: "transparent",
        headerFontSize: 16,
        headerHeight: 46,
        headerHeightSM: 46,
      },
      Table: {
        headerBg: colors.tableHeader,
        headerColor: colors.textSecondary,
        rowHoverBg: colors.rowHover,
        borderColor: colors.borderSoft,
        headerSplitColor: "transparent",
        cellPaddingBlockSM: 6,
        cellPaddingInlineSM: 8,
      },
      Button: {
        fontWeight: 500,
      },
      Tabs: {
        itemSelectedColor: "#2893B3",
        inkBarColor: "#2893B3",
        horizontalItemGutter: 18,
      },
      Statistic: {
        contentFontSize: 26,
        titleFontSize: 13,
      },
      Segmented: {
        itemSelectedBg: colors.segmented,
      },
    },
  };
}

export function AdminThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readMode);
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme);

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) =>
      setSystem(event.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const resolved: ResolvedTheme = mode === "auto" ? system : mode;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
  }, [resolved]);

  const value = useMemo<AdminThemeContextValue>(
    () => ({
      mode,
      resolved,
      setMode: (next) => {
        setModeState(next);
        try {
          window.localStorage.setItem(STORAGE_KEY, next);
        } catch {
          // Local storage may be unavailable.
        }
      },
    }),
    [mode, resolved],
  );

  const config = useMemo(() => themeConfig(resolved), [resolved]);

  return (
    <AdminThemeContext.Provider value={value}>
      <ConfigProvider locale={zhCN} theme={config}>
        {children}
      </ConfigProvider>
    </AdminThemeContext.Provider>
  );
}

export function useAdminTheme(): AdminThemeContextValue {
  const value = useContext(AdminThemeContext);
  if (!value) {
    throw new Error("useAdminTheme must be used inside AdminThemeProvider");
  }
  return value;
}
