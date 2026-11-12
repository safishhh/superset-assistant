import { useEffect, useMemo, useState } from "react";
import { Select, Tag } from "antd";
import type { CSSProperties } from "react";
import { api } from "./api";
import type { SupersetUser } from "./types";

export type UserOption = { value: string; label: string; hasData: boolean };

/**
 * 后台「用户」筛选选项 = 本地数据里出现过的用户名 ∪ Superset 全量用户。
 * Superset 列表拉取失败时自动退回只用本地列表，不影响页面。
 */
export function useUserOptions(localUsers: string[]): UserOption[] {
  const [supersetUsers, setSupersetUsers] = useState<SupersetUser[]>([]);

  useEffect(() => {
    let alive = true;
    api<{ items: SupersetUser[] }>("/superset-users")
      .then((data) => {
        if (alive) setSupersetUsers(data.items);
      })
      .catch(() => {
        // Superset 不可用时保持本地列表
      });
    return () => {
      alive = false;
    };
  }, []);

  return useMemo(() => {
    const map = new Map<string, UserOption>();
    localUsers.forEach((name) => {
      const key = name.toLowerCase();
      if (key) map.set(key, { value: name, label: name, hasData: true });
    });
    supersetUsers.forEach((user) => {
      const key = user.username.toLowerCase();
      const existing = map.get(key);
      const display = user.display_name
        ? `${user.username}（${user.display_name}）`
        : user.username;
      if (existing) {
        existing.label = display;
        existing.hasData = true;
      } else {
        map.set(key, { value: user.username, label: display, hasData: false });
      }
    });
    return [...map.values()].sort((left, right) =>
      left.value.localeCompare(right.value),
    );
  }, [localUsers, supersetUsers]);
}

export default function UserSelect({
  localUsers,
  value,
  onChange,
  width = 140,
  style,
}: {
  localUsers: string[];
  value: string | undefined;
  onChange: (value: string) => void;
  width?: number;
  style?: CSSProperties;
}) {
  const options = useUserOptions(localUsers);
  return (
    <Select
      placeholder="用户"
      value={value || undefined}
      onChange={(next) => onChange((next ?? "") as string)}
      style={{ width, ...style }}
      allowClear
      showSearch
      optionFilterProp="label"
      options={options.map((item) => ({ value: item.value, label: item.label }))}
      optionRender={(option) => {
        const item = options.find((entry) => entry.value === option.value);
        if (!item || item.hasData) return <span>{option.label}</span>;
        return (
          <span>
            {option.label}
            <Tag style={{ marginLeft: 6 }}>无记录</Tag>
          </span>
        );
      }}
    />
  );
}
