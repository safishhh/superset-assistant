export type KnowledgeRef = {
  id: number;
  scope: string;
  title: string;
  content: string;
  contentChars: number;
  truncated: boolean;
  source: string;
};

export type KnowledgeToolEntry = { name: string; result: unknown };

/** 从 search_knowledge 的工具结果里取出命中的知识条目（同一轮内按 id 去重）。 */
export function collectKnowledgeRefs(
  entries: KnowledgeToolEntry[],
): KnowledgeRef[] {
  const seen = new Set<string>();
  const refs: KnowledgeRef[] = [];
  for (const entry of entries) {
    if (entry.name !== "search_knowledge") continue;
    const data = (entry.result ?? {}) as Record<string, any>;
    const items = Array.isArray(data.items) ? data.items : [];
    for (const raw of items) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, any>;
      const id = Number(item.id);
      if (!Number.isFinite(id)) continue;
      const scope = item.scope === "employee" ? "employee" : "user";
      const key = `${scope}:${id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      refs.push({
        id,
        scope,
        title: String(item.title ?? `知识 #${id}`),
        content: String(item.content ?? ""),
        contentChars: Number(item.content_chars ?? 0),
        truncated: Boolean(item.truncated),
        source: String(item.source ?? "auto"),
      });
    }
  }
  return refs;
}
