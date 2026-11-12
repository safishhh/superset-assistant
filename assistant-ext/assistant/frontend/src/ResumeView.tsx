export default function ResumeView({
  question,
  text,
  toolCalls,
  elapsedMs,
  stopping,
  onStop,
}: {
  question: string;
  text: string;
  toolCalls: number;
  elapsedMs: number;
  stopping: boolean;
  onStop: () => void;
}) {
  const seconds = Math.max(0, Math.round(elapsedMs / 1000));
  return (
    <div className="sa-resume">
      <div className="sa-resume-head">
        <span className="sa-spinner" />
        <strong>后台生成中</strong>
        <span className="sa-resume-hint">
          关闭面板不会中断，完成后会自动显示完整回答
        </span>
        <span className="sa-header-spacer" />
        <button
          type="button"
          className="sa-history-btn sa-resume-stop"
          onClick={onStop}
          disabled={stopping}
        >
          {stopping ? "正在停止…" : "停止"}
        </button>
      </div>
      <div className="sa-resume-body">
        {question ? (
          <div className="sa-resume-q">
            <span className="sa-resume-label">你的问题</span>
            <div className="sa-resume-q-text">{question}</div>
          </div>
        ) : null}
        <div className="sa-resume-label">回答（已生成 {text.length} 字）</div>
        <div className="sa-resume-a">{text || "正在分析…"}</div>
        <div className="sa-resume-meta">
          {toolCalls ? `已执行 ${toolCalls} 步工具 · ` : ""}
          耗时 {seconds} 秒
        </div>
      </div>
    </div>
  );
}
