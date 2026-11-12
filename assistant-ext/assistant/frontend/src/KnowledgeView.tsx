import { useCallback, useEffect, useState } from "react";

import {
  KnowledgeItem,
  KnowledgeUsage,
  deleteKnowledge,
  listKnowledge,
  restoreKnowledge,
  saveKnowledge,
  updateKnowledge,
} from "./userApi";

function time(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value.slice(0, 16)
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

function quotaText(usage: KnowledgeUsage): string {
  const manual =
    usage.manual_max > 0
      ? `手动 ${usage.manual_used}/${usage.manual_max}`
      : `手动 ${usage.manual_used}（不限）`;
  const auto =
    usage.auto_max > 0
      ? `AI 记录 ${usage.auto_used}/${usage.auto_max}`
      : `AI 记录 ${usage.auto_used}（不限）`;
  return `${manual} · ${auto} · 回收站 ${usage.trash}`;
}

export default function KnowledgeView({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"active" | "trash">("active");
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [usage, setUsage] = useState<KnowledgeUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [condense, setCondense] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listKnowledge(tab);
      setItems(data.items);
      setUsage(data.usage ?? null);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  const resetForm = () => {
    setEditingId(null);
    setTitle("");
    setContent("");
    setCondense(false);
  };

  const startEdit = (item: KnowledgeItem) => {
    setEditingId(item.id);
    setTitle(item.title);
    setContent(item.content);
    setCondense(false);
    setNotice("");
  };

  const remove = async (id: number, purge = false) => {
    try {
      await deleteKnowledge(id, purge);
      setItems((current) => current.filter((item) => item.id !== id));
      if (editingId === id) resetForm();
      setConfirmId(null);
      setNotice(purge ? "已彻底删除" : "已移入回收站");
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const restore = async (id: number) => {
    try {
      await restoreKnowledge(id);
      setNotice("已恢复");
      await load();
    } catch (exc) {
      setNotice(exc instanceof Error ? exc.message : String(exc));
    }
  };

  const submit = async () => {
    if (!title.trim() || !content.trim()) {
      setNotice("标题和内容都要填");
      return;
    }
    setSaving(true);
    setNotice("");
    try {
      const mode = condense ? "summarize" : "raw";
      if (editingId !== null) {
        await updateKnowledge(editingId, title.trim(), content.trim(), mode);
        setNotice("已更新");
      } else {
        const saved = await saveKnowledge(title.trim(), content.trim(), mode);
        setNotice(saved.condensed ? "已保存（AI 精简后）" : "已保存");
      }
      resetForm();
      await load();
    } catch (exc) {
      // 409 = 条数已满，提示用户先清理
      setNotice(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  };

  const manualFull =
    usage !== null && usage.manual_max > 0 && usage.manual_used >= usage.manual_max;

  return (
    <div className="sa-history">
      <div className="sa-history-head">
        <button type="button" className="sa-history-btn" onClick={onClose}>
          返回对话
        </button>
        <strong>个人知识库</strong>
        <span className="sa-header-spacer" />
        <button type="button" className="sa-history-btn" onClick={() => void load()}>
          刷新
        </button>
      </div>

      {error ? <div className="sa-error">{error}</div> : null}

      <div className="sa-kb-tabs">
        <button
          type="button"
          className={tab === "active" ? "sa-kb-tab sa-kb-tab-active" : "sa-kb-tab"}
          onClick={() => setTab("active")}
        >
          生效中
        </button>
        <button
          type="button"
          className={tab === "trash" ? "sa-kb-tab sa-kb-tab-active" : "sa-kb-tab"}
          onClick={() => setTab("trash")}
        >
          回收站
        </button>
        {usage ? <span className="sa-kb-quota">{quotaText(usage)}</span> : null}
      </div>

      <div className="sa-history-body">
        {tab === "active" ? (
          <>
            <div className="sa-history-meta">
              仅自己可见。「手动」条目只有你自己能改，模型不会覆盖；对助手说
              “记住这个口径”由它提炼的条目算「AI 记录」，会归并、按使用度检索，也可删除。
            </div>

            <div className="sa-kb-editor">
              <div className="sa-kb-editor-title">
                {editingId !== null ? "编辑条目" : "新增条目"}
              </div>
              <input
                className="sa-kb-input"
                placeholder="标题（同标题会覆盖）"
                value={title}
                maxLength={200}
                onChange={(event) => setTitle(event.target.value)}
              />
              <textarea
                className="sa-kb-textarea"
                placeholder="内容：口径、定义、规则…"
                value={content}
                rows={4}
                maxLength={8000}
                onChange={(event) => setContent(event.target.value)}
              />
              <label className="sa-kb-check">
                <input
                  type="checkbox"
                  checked={condense}
                  onChange={(event) => setCondense(event.target.checked)}
                />
                <span>让 AI 精简后再保存（保留全部数字与口径，失败则按原文存）</span>
              </label>
              <div className="sa-kb-editor-actions">
                <button
                  type="button"
                  className="sa-history-btn sa-kb-primary"
                  disabled={saving}
                  onClick={() => void submit()}
                >
                  {saving ? "保存中…" : editingId !== null ? "保存修改" : "保存"}
                </button>
                <button
                  type="button"
                  className="sa-history-btn"
                  onClick={resetForm}
                >
                  {editingId !== null ? "取消编辑" : "清空"}
                </button>
                {notice ? <span className="sa-kb-notice">{notice}</span> : null}
              </div>
              {manualFull ? (
                <div className="sa-kb-notice">
                  手动条目已达上限，先到列表里删除一些（或改用「回收站」彻底清理）才能再保存。
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="sa-history-meta">
            回收站里的条目对你和助手都不可见，也不占用条数上限；超过保留期会自动彻底清理。
          </div>
        )}

        {loading ? (
          <div className="sa-history-meta">加载中…</div>
        ) : items.length === 0 ? (
          <div className="sa-history-meta">
            {tab === "active"
              ? "还没有知识条目。可以在上面手动新增，或对助手说：“记住：我们团队的 XX 定义是 YY。”"
              : "回收站是空的。"}
          </div>
        ) : (
          <div className="sa-history-messages">
            {items.map((item) => (
              <div className="sa-history-msg" key={item.id}>
                <div className="sa-history-msg-head">
                  <strong>{item.title}</strong>
                  {tab === "active" ? (
                    <span
                      className={
                        item.source === "manual"
                          ? "sa-kb-source sa-kb-source-manual"
                          : "sa-kb-source"
                      }
                    >
                      {item.source === "manual" ? "手动" : "AI 记录"}
                    </span>
                  ) : null}
                  <span>
                    {tab === "active" ? time(item.updated_at) : `删除于 ${time(item.deleted_at)}`}
                    {tab === "active" ? (
                      <button
                        type="button"
                        className="sa-history-btn"
                        onClick={() => startEdit(item)}
                        style={{ marginLeft: 8 }}
                      >
                        编辑
                      </button>
                    ) : null}
                    {confirmId === item.id ? (
                      <span>
                        {" "}
                        <button
                          type="button"
                          className="sa-history-danger"
                          onClick={() =>
                            void remove(item.id, tab === "trash")
                          }
                        >
                          {tab === "trash" ? "确认彻底删除" : "确认删除"}
                        </button>
                        {" "}
                        <button
                          type="button"
                          className="sa-history-btn"
                          onClick={() => setConfirmId(null)}
                        >
                          取消
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="sa-history-btn sa-history-delete"
                        onClick={() => setConfirmId(item.id)}
                        style={{ marginLeft: 6 }}
                      >
                        {tab === "trash" ? "彻底删除" : "删除"}
                      </button>
                    )}
                    {tab === "trash" ? (
                      <button
                        type="button"
                        className="sa-history-btn"
                        onClick={() => void restore(item.id)}
                        style={{ marginLeft: 6 }}
                      >
                        恢复
                      </button>
                    ) : null}
                  </span>
                </div>
                <div className="sa-history-text">{item.content}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
