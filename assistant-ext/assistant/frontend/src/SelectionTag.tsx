import type { SelectedBlock } from "./context";
import { selectionKindLabel } from "./selectionLabels";

function label(block: SelectedBlock): string {
  return `${selectionKindLabel(block.kind)} · ${block.title || "未命名"}`;
}

export default function SelectionTag({
  blocks,
  compact = false,
}: {
  blocks?: SelectedBlock[] | null;
  compact?: boolean;
}) {
  if (!blocks || blocks.length === 0) return null;
  return (
    <div className={`sa-msg-selection${compact ? " sa-msg-selection-compact" : ""}`}>
      <span className="sa-msg-selection-label">选中</span>
      {blocks.map((block, index) => (
        <span
          className="sa-msg-selection-chip"
          key={`${block.kind}-${block.chart_id || block.title}-${index}`}
          title={block.text || block.title}
        >
          {label(block)}
        </span>
      ))}
    </div>
  );
}
