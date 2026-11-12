import { lazy, Suspense, useEffect, useState } from "react";
import {
  Button,
  Layout,
  Menu,
  Result,
  Segmented,
  Spin,
  message,
} from "antd";
import { bootstrapSession, loadMe, logout } from "./api";
import type { AdminUser } from "./api";
import { AssistantAvatar } from "../../assistant-ext/assistant/frontend/src/AssistantAvatar";
import { useAdminTheme, type ThemeMode } from "./theme";

// 按页懒加载：13 个页面不再全部打进首屏 chunk
const OverviewPage = lazy(() => import("./pages/Overview"));
const AuditPage = lazy(() => import("./pages/Audit"));
const LogsPage = lazy(() => import("./pages/Logs"));
const AiCallsPage = lazy(() =>
  import("./pages/Logs").then((mod) => ({ default: mod.AiCallsPage })),
);
const ModelSettingsPage = lazy(() => import("./pages/ModelSettings"));
const UsageStatsPage = lazy(() => import("./pages/UsageStats"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const SkillsPage = lazy(() => import("./pages/Skills"));
const UsersPage = lazy(() => import("./pages/Users"));
const RolesPage = lazy(() => import("./pages/Roles"));
const EmployeesPage = lazy(() => import("./pages/Employees"));
const FeedbackPage = lazy(() => import("./pages/Feedback"));
const AgentLimitsPage = lazy(() => import("./pages/AgentLimits"));

const { Header, Sider, Content } = Layout;

const PAGE_META = {
  overview: { label: "概览", description: "请求、Token、成本与使用趋势" },
  models: {
    label: "模型配置",
    description: "Provider、模型、思考强度与限额",
  },
  "knowledge-settings": {
    label: "知识库设置",
    description: "知识库条数上限与自动沉淀策略",
  },
  "agent-limits": {
    label: "运行限制",
    description: "单次请求的工具调用次数与单次查询返回行数上限",
  },
  usage: { label: "用量统计", description: "用量明细/聚合与 Top 榜单" },
  users: {
    label: "用户",
    description: "Superset 用户、角色、分组与个人知识库",
  },
  roles: {
    label: "角色和权限",
    description: "按角色配置可用的 AI 牛马",
  },
  employees: {
    label: "AI 牛马",
    description: "AI 员工：人设 / 模型 / 技能 / 工具 / 知识库",
  },
  audit: { label: "审计日志", description: "对话、工具调用与管理操作留痕" },
  logs: { label: "运行日志", description: "Agent 文件日志，按天切分并自动刷新" },
  "ai-calls": {
    label: "AI 调用",
    description: "每次模型请求的耗时、Token、工具与状态",
  },
  skills: { label: "技能", description: "自定义 run_skill_* 工具与指令" },
  feedback: { label: "反馈", description: "回答级点赞点踩明细，用于效果评估" },
} as const;

type PageKey = keyof typeof PAGE_META;
// 仅 MENU 里实际用作 icon 的名称；其余 PageKey 不做菜单图标
type MenuIconName =
  | "overview"
  | "settings"
  | "usage"
  | "users"
  | "logs"
  | "skills"
  | "feedback";

type MenuItem = {
  key: string;
  label: string;
  icon?: MenuIconName;
  children?: Array<{ key: PageKey; label: string }>;
};

const MENU: MenuItem[] = [
  { key: "overview", label: "概览", icon: "overview" },
  {
    key: "settings",
    label: "设置",
    icon: "settings",
    children: [
      { key: "models", label: "模型配置" },
      { key: "knowledge-settings", label: "知识库设置" },
      { key: "agent-limits", label: "运行限制" },
    ],
  },
  { key: "usage", label: "用量统计", icon: "usage" },
  {
    key: "users-perms",
    label: "用户和权限",
    icon: "users",
    children: [
      { key: "users", label: "用户" },
      { key: "roles", label: "角色和权限" },
      { key: "employees", label: "AI 牛马" },
    ],
  },
  {
    key: "logs-group",
    label: "日志",
    icon: "logs",
    children: [
      { key: "audit", label: "审计日志" },
      { key: "logs", label: "运行日志" },
      { key: "ai-calls", label: "AI 调用" },
    ],
  },
  { key: "skills", label: "技能", icon: "skills" },
  { key: "feedback", label: "反馈", icon: "feedback" },
];

const ALIASES: Record<string, PageKey> = {
  limits: "models",
  rankings: "usage",
  settings: "knowledge-settings",
  knowledge: "users",
};

function pageFromHash(): PageKey {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const key = (ALIASES[raw] ?? raw) as PageKey;
  return key in PAGE_META ? key : "overview";
}

function MenuIcon({ name }: { name: MenuIconName }) {
  const common = {
    width: 15,
    height: 15,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "overview":
      return (
        <svg {...common}>
          <rect x="3.5" y="3.5" width="7" height="7" rx="1.6" />
          <rect x="13.5" y="3.5" width="7" height="7" rx="1.6" />
          <rect x="3.5" y="13.5" width="7" height="7" rx="1.6" />
          <rect x="13.5" y="13.5" width="7" height="7" rx="1.6" />
        </svg>
      );
    case "usage":
      return (
        <svg {...common}>
          <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
        </svg>
      );
    case "skills":
      return (
        <svg {...common}>
          <path d="m12 3 2.4 5.3 5.6.7-4.2 3.9 1.1 5.5L12 15.6l-4.9 2.8 1.1-5.5L4 9l5.6-.7z" />
        </svg>
      );
    case "settings":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3.2" />
          <path d="M12 3v2.4M12 18.6V21M3 12h2.4M18.6 12H21M5.6 5.6l1.7 1.7M16.7 16.7l1.7 1.7M18.4 5.6l-1.7 1.7M7.3 16.7l-1.7 1.7" />
        </svg>
      );
    case "users":
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3.4" />
          <path d="M2.8 20c0-3.2 2.8-5.4 6.2-5.4s6.2 2.2 6.2 5.4" />
          <path d="M16 5.2a3.2 3.2 0 0 1 0 6.2M17.4 14.8c2.2.5 3.8 2.2 3.8 4.6" />
        </svg>
      );
    case "logs":
      return (
        <svg {...common}>
          <path d="M6 3.5h8.5l4 4v13H6z" />
          <path d="M14.5 3.5v4h4M9 11.5h6M9 15h6M9 8h2" />
        </svg>
      );
    case "feedback":
      return (
        <svg {...common}>
          <path d="M4.5 6.3a1.8 1.8 0 0 1 1.8-1.8h11.4a1.8 1.8 0 0 1 1.8 1.8v7.4a1.8 1.8 0 0 1-1.8 1.8H10l-4.2 3.6a.45.45 0 0 1-.74-.34z" />
          <path d="M8.5 9h7M8.5 12h4.5" />
        </svg>
      );
  }
}

function NavToggleIcon({ collapsed }: { collapsed: boolean }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  return collapsed ? (
    <svg {...common}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
      <path d="M9 4.5v15M13.5 9.5 17 12l-3.5 2.5" />
    </svg>
  ) : (
    <svg {...common}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
      <path d="M9 4.5v15M16.5 9.5 13 12l3.5 2.5" />
    </svg>
  );
}

function supersetUrl(): string {
  return `${window.location.protocol}//${window.location.hostname}:8088/`;
}

export default function App() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [me, setMe] = useState<AdminUser | null>(null);
  const [page, setPage] = useState<PageKey>(pageFromHash);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const { mode, setMode } = useAdminTheme();

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    // bootstrapSession 还没消费一次性 ticket 时不能覆写 hash，否则登录流程失效
    if (window.location.hash.startsWith("#ticket=")) return;
    const target = `#/${page}`;
    if (window.location.hash !== target) {
      window.history.replaceState(null, "", target);
    }
  }, [page, ready]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const ok = await bootstrapSession();
        if (!ok) {
          if (alive) setReady(false);
          return;
        }
        const user = await loadMe();
        if (alive) {
          setMe(user);
          setReady(true);
        }
      } catch (exc) {
        message.error(exc instanceof Error ? exc.message : String(exc));
        if (alive) setReady(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const unauthorized = () => setReady(false);
    window.addEventListener("sa-admin-unauthorized", unauthorized);
    return () =>
      window.removeEventListener("sa-admin-unauthorized", unauthorized);
  }, []);

  if (ready === null) {
    return (
      <div className="center">
        <div className="loading-card">
          <AssistantAvatar className="loading-avatar" follow={false} />
          <Spin />
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="center">
        <div className="auth-card">
          <div className="auth-brand">
            <AssistantAvatar className="auth-avatar" follow={false} />
            <span>AI 管理后台</span>
          </div>
          <Result
            status="403"
            title="请从 Superset 助手进入"
            subTitle="AI 管理后台沿用 Superset 登录。请打开数据分析助手，点击头部的盾牌图标进入。"
            extra={
              <Button type="primary" href={supersetUrl()}>
                打开 Superset
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  const current = PAGE_META[page];
  const initial = (me?.username || "A").slice(0, 1).toUpperCase();

  return (
    <Layout className="admin-shell">
      <Sider
        theme="light"
        width={200}
        collapsedWidth={64}
        collapsed={navCollapsed}
        trigger={null}
        className="admin-sider"
      >
        <div className="brand">
          <AssistantAvatar className="brand-avatar" />
          <div className="brand-text">
            <div className="brand-title">Superset Assistant</div>
            <div className="brand-sub">AI 管理后台</div>
          </div>
        </div>
        <Menu
          mode="inline"
          className="admin-menu"
          selectedKeys={[page]}
          defaultOpenKeys={["settings", "users-perms", "logs-group"]}
          items={MENU.map((item) => ({
            key: item.key,
            label: item.label,
            icon: item.icon ? (
              <span className="anticon" aria-hidden>
                <MenuIcon name={item.icon} />
              </span>
            ) : undefined,
            children: item.children?.map((child) => ({
              key: child.key,
              label: child.label,
            })),
          }))}
          onClick={(item) => {
            if (item.key in PAGE_META) setPage(item.key as PageKey);
          }}
        />
        <div className="sider-footer">
          <span>审计保留 90 天</span>
          <span>v0.1</span>
        </div>
      </Sider>
      <Layout className="admin-main">
        <Header className="admin-header">
          <button
            type="button"
            className="nav-toggle"
            title={navCollapsed ? "展开导航" : "收起导航"}
            aria-label={navCollapsed ? "展开导航" : "收起导航"}
            onClick={() => setNavCollapsed((value) => !value)}
          >
            <NavToggleIcon collapsed={navCollapsed} />
          </button>
          <div className="header-heading">
            <span className="header-eyebrow">AI 管理后台</span>
            <span className="header-page">{current.label}</span>
          </div>
          <span className="header-desc">{current.description}</span>
          <span className="header-spacer" />
          <Segmented
            className="theme-switch"
            size="small"
            value={mode}
            onChange={(value) => setMode(value as ThemeMode)}
            options={[
              { label: "自动", value: "auto" },
              { label: "浅色", value: "light" },
              { label: "深色", value: "dark" },
            ]}
          />
          <div className="header-user">
            <span className="user-avatar">{initial}</span>
            <span className="user-name">{me?.username}</span>
          </div>
          <Button
            size="small"
            type="text"
            className="logout-btn"
            onClick={() => logout()}
          >
            退出
          </Button>
        </Header>
        <Content className="admin-content">
          <Suspense fallback={<div style={{ padding: 48, textAlign: "center" }}><Spin /></div>}>
          {page === "overview" ? <OverviewPage /> : null}
          {page === "models" ? <ModelSettingsPage /> : null}
          {page === "knowledge-settings" ? <SettingsPage /> : null}
          {page === "agent-limits" ? <AgentLimitsPage /> : null}
          {page === "usage" ? <UsageStatsPage /> : null}
          {page === "users" ? <UsersPage /> : null}
          {page === "roles" ? <RolesPage /> : null}
          {page === "employees" ? <EmployeesPage /> : null}
          {page === "audit" ? <AuditPage /> : null}
          {page === "logs" ? <LogsPage /> : null}
          {page === "ai-calls" ? <AiCallsPage /> : null}
          {page === "skills" ? <SkillsPage /> : null}
          {page === "feedback" ? <FeedbackPage /> : null}
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
}
