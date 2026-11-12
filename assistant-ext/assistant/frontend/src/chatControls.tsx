import React, {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useAssistantState, useMessage } from "@assistant-ui/react";

import type { SelectedBlock } from "./context";

export type EmployeeInfo = {
  id: number;
  username: string;
  nickname: string;
  title: string;
  avatar: string;
  intro: string;
  greeting: string;
  model_id?: number | null;
  model_ids?: number[] | null;
};

export type ModelInfo = {
  id: number;
  display_name: string;
  model_name: string;
  provider_name: string;
  is_default: boolean;
  supports_tools: boolean;
};

export const EMPLOYEE_KEY = "sa-assistant-employee";
export const MODEL_KEY = "sa-assistant-model";
export const REASONING_KEY = "sa-assistant-reasoning";

export type ReasoningEffort = "default" | "low" | "medium" | "high";

const REASONING_OPTIONS: Array<{
  value: ReasoningEffort;
  label: string;
  hint: string;
}> = [
  { value: "default", label: "默认", hint: "不额外指定，由模型决定" },
  { value: "low", label: "低", hint: "更快，适合简单问题" },
  { value: "medium", label: "中", hint: "速度与深度平衡" },
  { value: "high", label: "高", hint: "更深入，耗时更长" },
];

export function readReasoningEffort(): ReasoningEffort {
  try {
    const raw = window.localStorage.getItem(REASONING_KEY);
    if (raw === "low" || raw === "medium" || raw === "high") return raw;
  } catch {
    // ignore
  }
  return "default";
}

export function readEmployeeId(): number | null {
  try {
    const raw = window.localStorage.getItem(EMPLOYEE_KEY);
    const value = raw ? Number(raw) : NaN;
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function readModelId(): number | null {
  try {
    const raw = window.localStorage.getItem(MODEL_KEY);
    const value = raw ? Number(raw) : NaN;
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export const EmployeeContext = createContext<EmployeeInfo | null>(null);

export const SelectionTurnsContext = createContext<SelectedBlock[][]>([]);

export function useTurnSelection(role: "user" | "assistant"): SelectedBlock[] {
  const turns = useContext(SelectionTurnsContext);
  const message = useMessage();
  const messages = useAssistantState(({ thread }) => thread.messages);
  return useMemo(() => {
    const index = messages.findIndex((item) => item.id === message.id);
    if (index < 0) return [];
    const upto = role === "assistant" ? index - 1 : index;
    let userCount = 0;
    for (let i = 0; i <= upto; i += 1) {
      if (messages[i]?.role === "user") userCount += 1;
    }
    return userCount > 0 ? turns[userCount - 1] ?? [] : [];
  }, [turns, messages, message.id, role]);
}

function EmployeeAvatar({ avatar }: { avatar?: string }) {
  if (avatar && /^https?:/i.test(avatar)) {
    return <img src={avatar} alt="" />;
  }
  return <>{avatar || "🤖"}</>;
}


/**
 * 下拉菜单左边缘与按钮左边缘对齐。菜单相对整条工具行定位（避免窄面板被裁），
 * 所以这里把按钮相对行的偏移写成 left；贴近面板右缘时再整体左移。
 */
function useMenuLeftAlign(
  rootRef: React.RefObject<HTMLElement | null>,
  open: boolean,
) {
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!open || !root) return;
    const menu = root.querySelector<HTMLElement>(
      ".sa-model-menu, .sa-employee-menu",
    );
    const bar = root.closest(".sa-composer-bar");
    if (!menu || !bar) return;
    const barRect = bar.getBoundingClientRect();
    const offset = root.getBoundingClientRect().left - barRect.left;
    const panel = bar.closest(".sa-panel");
    const limit =
      (panel ? panel.getBoundingClientRect().right : barRect.right) - 8;
    const place = (left: number) => {
      menu.style.left = `${Math.round(left)}px`;
      const overflow = menu.getBoundingClientRect().right - limit;
      if (overflow > 0) place(left - overflow);
    };
    place(Math.max(0, offset));
  }, [rootRef, open]);
}
export function EmployeePicker({
  employees,
  value,
  onChange,
}: {
  employees: EmployeeInfo[];
  value: number | null;
  onChange: (value: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const current = employees.find((item) => item.id === value) ?? null;

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  useMenuLeftAlign(rootRef, open);

  const choose = (next: number) => {
    setOpen(false);
    if (next !== value) onChange(next);
  };

  return (
    <span className="sa-employee-picker" ref={rootRef}>
      <button
        type="button"
        className="sa-employee-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={
          current
            ? `${current.nickname}${current.title ? ` @${current.title}` : ""}`
            : "选择 AI 牛马"
        }
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="sa-employee-avatar" aria-hidden>
          <EmployeeAvatar avatar={current?.avatar} />
        </span>
        <span className="sa-employee-name">
          {current ? current.nickname : "选择 AI 牛马"}
        </span>
        {current?.title ? (
          <span className="sa-employee-title">@{current.title}</span>
        ) : null}
        <span className="sa-employee-caret" aria-hidden>
          ▾
        </span>
      </button>
      {open ? (
        <div className="sa-employee-menu" role="listbox" aria-label="选择 AI 员工">
          {employees.map((item) => (
            <button
              key={item.id}
              type="button"
              role="option"
              aria-selected={item.id === value}
              className={[
                "sa-employee-option",
                item.id === value ? "sa-employee-option-active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => choose(item.id)}
            >
              <span className="sa-employee-avatar" aria-hidden>
                <EmployeeAvatar avatar={item.avatar} />
              </span>
              <span className="sa-employee-option-text">
                <span className="sa-employee-option-name">{item.nickname}</span>
                <span className="sa-employee-option-title">
                  {item.title ? `@${item.title}` : item.username}
                </span>
              </span>
              {item.id === value ? (
                <span className="sa-employee-check">✓</span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}

export function ModelPicker({
  models,
  value,
  defaultModelId,
  defaultLabel,
  disabled,
  onChange,
}: {
  models: ModelInfo[];
  value: number | null;
  defaultModelId?: number | null;
  defaultLabel?: string;
  disabled?: boolean;
  onChange: (value: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const defaultModel =
    (defaultModelId
      ? models.find((item) => item.id === defaultModelId)
      : null) ??
    models.find((item) => item.is_default) ??
    models[0] ??
    null;
  const current = models.find((item) => item.id === value) ?? defaultModel;
  const missingBound = disabled && value !== null && !current;

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  useMenuLeftAlign(rootRef, open);

  if (models.length === 0) return null;
  const choose = (next: number | null) => {
    setOpen(false);
    if (next !== value) onChange(next);
  };

  return (
    <span className="sa-model-picker" ref={rootRef}>
      <button
        type="button"
        className="sa-model-trigger"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={
          disabled
            ? missingBound
              ? "当前员工没有可用模型，请到 AI 管理后台检查"
              : "当前员工只有固定可用模型"
            : "切换模型"
        }
        onClick={() => setOpen((currentOpen) => !currentOpen)}
      >
        <span className="sa-model-icon" aria-hidden>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="6" y="6" width="12" height="12" rx="2.5" />
            <path d="M9 2.8v3.2M15 2.8v3.2M9 18v3.2M15 18v3.2M2.8 9H6M2.8 15H6M18 9h3.2M18 15h3.2" />
          </svg>
        </span>
        <span className="sa-model-name">
          {missingBound
            ? "员工绑定模型（不可用）"
            : current?.display_name || "默认模型"}
        </span>
        {current?.is_default ? (
          <span className="sa-model-badge">默认</span>
        ) : null}
        <span className="sa-model-caret" aria-hidden>
          ▾
        </span>
      </button>
      {open && !disabled ? (
        <div className="sa-model-menu" role="listbox" aria-label="选择模型">
          <button
            type="button"
            role="option"
            aria-selected={value === null}
            className={`sa-model-option${
              value === null ? " sa-model-option-active" : ""
            }`}
            onClick={() => choose(null)}
          >
            <span className="sa-model-option-text">
              <span className="sa-model-option-name">
                {defaultLabel || "跟随系统默认"}
              </span>
              <span className="sa-model-option-sub">
                {defaultModel?.display_name || "默认模型"}
              </span>
            </span>
            {value === null ? <span className="sa-model-check">✓</span> : null}
          </button>
          {models.map((model) => (
            <button
              type="button"
              role="option"
              key={model.id}
              aria-selected={model.id === value}
              className={`sa-model-option${
                model.id === value ? " sa-model-option-active" : ""
              }`}
              onClick={() => choose(model.id)}
            >
              <span className="sa-model-option-text">
                <span className="sa-model-option-name">{model.display_name}</span>
                <span className="sa-model-option-sub">
                  {model.model_name}
                  {model.supports_tools ? "" : " · 无工具"}
                </span>
              </span>
              {model.is_default ? (
                <span className="sa-model-check">默认</span>
              ) : model.id === value ? (
                <span className="sa-model-check">✓</span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}

export function ReasoningPicker({
  value,
  onChange,
}: {
  value: ReasoningEffort;
  onChange: (value: ReasoningEffort) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const current =
    REASONING_OPTIONS.find((item) => item.value === value) ??
    REASONING_OPTIONS[0];

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);
  useMenuLeftAlign(rootRef, open);

  const choose = (next: ReasoningEffort) => {
    setOpen(false);
    if (next !== value) onChange(next);
  };

  return (
    <span className="sa-reasoning-picker" ref={rootRef}>
      <button
        type="button"
        className="sa-model-trigger sa-reasoning-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={`思考强度：${current.label}（${current.hint}）`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="sa-reasoning-icon" aria-hidden>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
          </svg>
        </span>
        <span className="sa-reasoning-prefix">思考</span>
        <span className="sa-reasoning-name">{current.label}</span>
        <span className="sa-model-caret" aria-hidden>
          ▾
        </span>
      </button>
      {open ? (
        <div
          className="sa-model-menu sa-reasoning-menu"
          role="listbox"
          aria-label="思考强度"
        >
          {REASONING_OPTIONS.map((item) => (
            <button
              type="button"
              role="option"
              key={item.value}
              aria-selected={item.value === value}
              className={`sa-model-option${
                item.value === value ? " sa-model-option-active" : ""
              }`}
              onClick={() => choose(item.value)}
            >
              <span className="sa-model-option-text">
                <span className="sa-model-option-name">{item.label}</span>
                <span className="sa-model-option-sub">{item.hint}</span>
              </span>
              {item.value === value ? (
                <span className="sa-model-check">✓</span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}
