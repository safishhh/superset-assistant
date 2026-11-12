import { useEffect, useState } from "react";

import type { KnowledgeRef } from "./knowledgeRefs";

export type KnowledgeLoader = (scope: string, id: number) => Promise<string>;

const SOURCE_LABELS: Record<string, string> = {
  manual: "手动记录",
  auto: "AI 记录",
  employee: "AI 牛马知识库",
};

export default function KnowledgeRefs({
  items,
  loadContent,
}: {
  items: KnowledgeRef[];
  loadContent?: KnowledgeLoader;
}) {
  const [active, setActive] = useState<KnowledgeRef | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!active || !loadContent) return undefined;
    let alive = true;
    setLoading(true);
    setContent("");
    loadContent(active.scope, active.id)
      .then((text) => {
        if (alive) setContent(text);
      })
      .catch(() => {
        if (alive) setContent("");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [active, loadContent]);

  useEffect(() => {
    if (!active) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActive(null);
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
    };
  }, [active]);

  if (!items.length) return null;
  const text = content || active?.content || "";
  const truncated =
    Boolean(active?.truncated) && content.length < (active?.contentChars ?? 0);

  return (
    <>
      <div className="sa-kb-refs">
        <span className="sa-kb-ref-label">参考知识库</span>
        {items.map((item) => (
          <button
            key={`${item.scope}-${item.id}`}
            type="button"
            className="sa-kb-ref-chip"
            title="查看这条知识的内容"
            onClick={() => setActive(item)}
          >
            {item.title}
          </button>
        ))}
      </div>
      {active ? (
        <div
          className="sa-kb-modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={active.title}
          onClick={() => setActive(null)}
        >
          <div
            className="sa-kb-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="sa-kb-modal-head">
              <strong className="sa-kb-modal-title">{active.title}</strong>
              <button
                type="button"
                className="sa-kb-modal-close"
                aria-label="关闭"
                onClick={() => setActive(null)}
              >
                ×
              </button>
            </div>
            <div className="sa-kb-modal-meta">
              {SOURCE_LABELS[active.source] ?? active.source}
              {active.scope === "employee" ? " · AI 牛马知识库" : ""}
              {active.contentChars ? ` · ${active.contentChars} 字` : ""}
            </div>
            <div className="sa-kb-modal-body">
              {loading ? "加载中…" : text || "（无内容）"}
              {truncated ? (
                <div className="sa-kb-modal-note">仅显示前 600 字。</div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
