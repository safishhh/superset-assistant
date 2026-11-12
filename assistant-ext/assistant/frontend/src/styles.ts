const CSS = `
.sa-panel,
.sa-trigger {
  --sa-bg: #ffffff;
  --sa-bg-container: #ffffff;
  --sa-bg-soft: #f8fafc;
  --sa-bg-hover: #f1f5f9;
  --sa-fg: #0f172a;
  --sa-fg-soft: #475569;
  --sa-fg-muted: #64748b;
  --sa-border: #e2e8f0;
  --sa-border-strong: #cbd5e1;
  --sa-accent: #2563eb;
  --sa-accent-soft: #dbeafe;
  --sa-primary-border: #2563eb;
  --sa-on-accent: #ffffff;
  --sa-avatar-accent: var(--sa-accent);
  --sa-danger: #dc2626;
  --sa-danger-soft: #fee2e2;
  --sa-success: #16a34a;
  --sa-success-soft: #dcfce7;
  --sa-warn: #b45309;
  --sa-warn-soft: #fef3c7;
  --sa-radius: 10px;
  --sa-radius-lg: 14px;
  --sa-radius-panel: 18px;
  --sa-shadow: 0 18px 48px rgba(15, 23, 42, 0.16);
  --sa-font: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-family: var(--sa-font);
}

.sa-panel,
.sa-panel *,
.sa-panel *::before,
.sa-panel *::after,
.sa-trigger,
.sa-trigger * {
  box-sizing: border-box;
}

/* 收起态：吉祥物直接浮在页面边缘，不再套圆角底板 */
.sa-trigger {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 2147483000;
  width: 72px;
  height: 72px;
  border: 0;
  background: none;
  box-shadow: none;
  cursor: pointer;
  display: inline-flex;
  align-items: flex-end;
  justify-content: center;
  box-sizing: border-box;
  padding: 0;
  overflow: visible;
  touch-action: none;
  user-select: none;
  transition: transform 0.18s ease, left 0.2s ease, top 0.2s ease;
}
.sa-avatar {
  display: block;
}
.sa-trigger-avatar {
  width: 100%;
  height: 100%;
  display: block;
  filter: drop-shadow(0 6px 14px rgba(15, 23, 42, 0.22));
}
.sa-trigger.sa-dragging {
  transition: none;
  cursor: grabbing;
  transform: scale(1.05);
}
/* 贴边静止超时后藏起 1/3，鼠标移到边缘即滑回 */
.sa-trigger.sa-trigger-left.sa-trigger-dim {
  transform: translateX(-33.334%);
}
.sa-trigger.sa-trigger-right.sa-trigger-dim {
  transform: translateX(33.334%);
}
.sa-trigger:hover {
  transform: translateY(-2px) scale(1.03);
}
.sa-trigger.sa-trigger-left.sa-trigger-dim:hover,
.sa-trigger.sa-trigger-right.sa-trigger-dim:hover {
  transform: translateY(-2px) scale(1.02);
}

.sa-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  transition: opacity 0.15s ease;
  height: 100%;
  min-height: 360px;
  background: var(--sa-bg);
  color: var(--sa-fg);
  font-size: 13px;
  line-height: 1.55;
  overflow: hidden;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-panel);
  box-shadow: var(--sa-shadow);
}

.sa-panel.sa-docked {
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

/* 停靠面板宽度上限为视口 45%（宿主 Splitter 只限制了最小宽度） */
.ant-splitter-panel:has(.sa-panel.sa-docked) {
  max-width: 45vw !important;
}

.sa-panel.sa-fullscreen {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  max-width: none;
  max-height: none;
  z-index: 2147483002;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.sa-thread {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
}

.sa-parts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.sa-msg .sa-error {
  margin: 0;
}

.sa-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 10px 6px 12px;
  border-bottom: 1px solid var(--sa-border);
  background: var(--sa-bg);
  flex: 0 0 auto;
}
/* 标题行放窗口控制，管理/历史/知识库/新对话单独一行，标题不再被挤掉 */
.sa-header-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sa-header-tools {
  justify-content: flex-end;
  gap: 2px;
}
.sa-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  flex: 1 1 auto;
}
.sa-brand-avatar {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  overflow: hidden;
  flex: 0 0 auto;
  box-shadow: 0 0 0 1px var(--sa-border);
  display: block;
}
.sa-header-title {
  min-width: 0;
  overflow: hidden;
}
.sa-title {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: 0.1px;
  margin: 0;
  white-space: nowrap;
}
.sa-subtitle {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  margin-top: 1px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-header-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
}
.sa-header-spacer { flex: 1 1 auto; }
.sa-icon-btn {
  border: 0;
  background: transparent;
  color: var(--sa-fg-soft);
  border-radius: 8px;
  width: 28px;
  height: 28px;
  padding: 0;
  cursor: pointer;
  line-height: 1;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  transition: background 0.15s ease, color 0.15s ease;
}
.sa-icon-btn svg { display: block; }
.sa-icon-btn:hover {
  background: var(--sa-bg-hover);
  color: var(--sa-fg);
}
.sa-icon-btn-active {
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
}
.sa-icon-btn-close:hover {
  background: var(--sa-danger-soft);
  color: var(--sa-danger);
}

.sa-export-wrap { position: relative; display: inline-flex; }
.sa-export-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 60;
  min-width: 148px;
  padding: 4px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg);
  box-shadow: var(--sa-shadow);
}
.sa-export-item {
  display: block;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--sa-fg-soft);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.sa-export-item:hover { background: var(--sa-bg-hover); color: var(--sa-fg); }
.sa-export-menu-up {
  top: auto;
  bottom: calc(100% + 6px);
}

.sa-messages {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 25px 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scroll-behavior: smooth;
  scrollbar-width: thin;
  scrollbar-color: var(--sa-border-strong) transparent;
}
.sa-messages > .sa-msg,
.sa-messages > .sa-thinking {
  width: 100%;
  max-width: 880px;
  margin-left: auto;
  margin-right: auto;
}
.sa-empty {
  width: 100%;
  max-width: 560px;
  margin: auto auto;
  padding: 22px 8px;
  text-align: center;
  color: var(--sa-fg-muted);
}
.sa-empty-avatar {
  width: 72px;
  height: 72px;
  margin: 0 auto 12px;
  display: block;
  filter: drop-shadow(0 10px 18px rgba(15, 23, 42, 0.16));
}
.sa-suggestions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 18px;
}
.sa-suggestion {
  border: 1px solid var(--sa-border);
  background: var(--sa-bg-soft);
  color: var(--sa-fg-soft);
  border-radius: var(--sa-radius-lg);
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
  font-size: 12px;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.sa-suggestion:hover {
  border-color: var(--sa-primary-border);
  background: var(--sa-accent-soft);
  color: var(--sa-fg);
}

.sa-msg { display: flex; flex-direction: column; gap: 8px; }
.sa-msg-user { align-items: flex-end; }
.sa-msg-assistant {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 8px;
}
.sa-assistant-avatar {
  width: 32px;
  height: 32px;
  border-radius: 11px;
  overflow: hidden;
  flex: 0 0 auto;
  margin-top: 2px;
  box-shadow: 0 0 0 1px var(--sa-border);
  background: var(--sa-bg-soft);
}
.sa-assistant-avatar .sa-avatar {
  width: 100%;
  height: 100%;
}
.sa-assistant-body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sa-bubble {
  max-width: min(86%, 620px);
  padding: 10px 13px;
  border-radius: 18px 18px 5px 18px;
  background: var(--sa-accent);
  color: var(--sa-on-accent);
  white-space: pre-wrap;
  word-break: break-word;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.1);
}
.sa-assistant-block {
  background: var(--sa-bg);
  color: var(--sa-fg);
  word-break: break-word;
}

.sa-md { font-size: 13px; }
.sa-md p { margin: 0 0 8px; }
.sa-md p:last-child { margin-bottom: 0; }
.sa-md h1, .sa-md h2, .sa-md h3, .sa-md h4 {
  font-size: 13.5px;
  margin: 12px 0 6px;
}
.sa-md ul, .sa-md ol { margin: 4px 0 8px; padding-left: 20px; }
.sa-md li { margin: 2px 0; }
.sa-md code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  background: var(--sa-bg-soft);
  border: 1px solid var(--sa-border);
  border-radius: 4px;
  padding: 1px 4px;
}
.sa-md pre {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: var(--sa-radius);
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 11.5px;
  line-height: 1.5;
}
.sa-md pre code {
  background: transparent;
  border: 0;
  padding: 0;
  color: inherit;
}
.sa-md table {
  border-collapse: collapse;
  width: 100%;
  font-size: 11.5px;
  margin: 6px 0;
}
.sa-md th, .sa-md td {
  border: 1px solid var(--sa-border);
  padding: 4px 6px;
  text-align: left;
}
.sa-md th { background: var(--sa-bg-soft); }

.sa-history-transcript {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 2px 12px;
}
.sa-employee-picker {
  position: relative;
  display: inline-flex;
  align-self: center;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 40%;
}
.sa-employee-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--sa-border);
  border-radius: 999px;
  background: var(--sa-bg-container);
  color: var(--sa-fg-soft);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  overflow: hidden;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.sa-employee-trigger:hover { border-color: var(--sa-border-strong); }
.sa-employee-trigger[aria-expanded="true"] {
  border-color: var(--sa-primary-border);
  background: var(--sa-bg);
}
.sa-employee-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  z-index: 30;
  min-width: 208px;
  max-width: 280px;
  max-height: 264px;
  overflow-y: auto;
  padding: 4px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg);
  box-shadow: var(--sa-shadow);
}
.sa-employee-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 3px 8px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--sa-fg-soft);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.sa-employee-option:hover { background: var(--sa-bg-hover); }
.sa-employee-option-active {
  background: var(--sa-accent-soft);
  color: var(--sa-fg);
}
.sa-employee-option-active .sa-employee-option-title { color: var(--sa-fg-soft); }
.sa-employee-option-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sa-employee-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.sa-employee-option-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-employee-check {
  margin-left: auto;
  color: var(--sa-accent);
  font-size: 11px;
}
.sa-employee-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--sa-accent-soft);
  font-size: 12px;
  flex: 0 0 auto;
  overflow: hidden;
}
.sa-employee-avatar img { width: 100%; height: 100%; object-fit: cover; }
.sa-employee-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-employee-title {
  color: var(--sa-fg-muted);
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-employee-caret { color: var(--sa-fg-muted); font-size: 9px; flex: 0 0 auto; }
.sa-model-picker {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 190px;
}
.sa-model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 100%;
  height: 24px;
  padding: 0 8px;
  border: 1px solid var(--sa-border);
  border-radius: 999px;
  background: var(--sa-bg-container);
  color: var(--sa-fg-soft);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  overflow: hidden;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.sa-model-trigger:hover { border-color: var(--sa-border-strong); }
.sa-model-trigger[aria-expanded="true"] {
  border-color: var(--sa-primary-border);
  background: var(--sa-bg);
}
.sa-model-trigger:disabled {
  cursor: default;
  opacity: 0.72;
}
.sa-model-icon {
  display: inline-flex;
  flex: 0 0 auto;
  color: var(--sa-fg-muted);
}
.sa-model-name {
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-model-badge {
  flex: 0 0 auto;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
  font-size: 9px;
  line-height: 14px;
}
.sa-model-caret {
  flex: 0 0 auto;
  color: var(--sa-fg-muted);
  font-size: 9px;
}
.sa-model-menu {
  position: absolute;
  left: 0;
  top: calc(100% + 6px);
  z-index: 80;
  min-width: 236px;
  max-width: 320px;
  max-height: 280px;
  overflow-y: auto;
  padding: 3px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg);
  box-shadow: var(--sa-shadow);
}
.sa-model-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 3px 8px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--sa-fg-soft);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.sa-model-option:hover { background: var(--sa-bg-hover); }
.sa-model-option-active {
  background: var(--sa-accent-soft);
  color: var(--sa-fg);
}
.sa-model-option-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sa-model-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.sa-model-option-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-model-check {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--sa-accent);
  font-size: 10.5px;
}
.sa-reasoning-picker {
  position: relative;
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  max-width: 88px;
}
.sa-reasoning-trigger {
  gap: 4px;
  padding: 0 7px;
  max-width: 100%;
}
.sa-reasoning-icon {
  display: inline-flex;
  flex: 0 0 auto;
  color: var(--sa-fg-muted);
}
.sa-reasoning-prefix {
  flex: 0 0 auto;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-reasoning-name {
  color: var(--sa-fg);
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-reasoning-menu {
  min-width: 190px;
  max-width: 230px;
}
@media (max-width: 420px) {
  .sa-model-picker { max-width: 128px; }
  .sa-model-badge { display: none; }
  .sa-reasoning-picker { max-width: 52px; }
  .sa-reasoning-prefix { display: none; }
}
.sa-empty-emoji {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 14px;
  background: var(--sa-accent-soft);
  font-size: 24px;
  margin-bottom: 8px;
}
.sa-kb-editor {
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  background: var(--sa-bg-soft);
  padding: 8px 10px;
  margin-bottom: 10px;
}
.sa-kb-editor-title {
  font-size: 11px;
  color: var(--sa-fg-muted);
  margin-bottom: 6px;
}
.sa-kb-input,
.sa-kb-textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--sa-border);
  border-radius: 8px;
  background: var(--sa-bg);
  color: var(--sa-fg);
  font-size: 12px;
  font-family: var(--sa-font);
  padding: 6px 8px;
  margin-bottom: 6px;
  resize: vertical;
}
.sa-kb-input:focus,
.sa-kb-textarea:focus {
  outline: none;
  border-color: var(--sa-primary-border);
}
.sa-kb-editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sa-kb-primary {
  background: var(--sa-accent);
  border-color: var(--sa-accent);
  color: var(--sa-on-accent);
}
.sa-kb-notice { font-size: 11px; color: var(--sa-fg-muted); }
.sa-kb-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px 0;
}
.sa-kb-tab {
  border: 1px solid var(--sa-border);
  border-bottom: 0;
  border-radius: 10px 10px 0 0;
  background: var(--sa-bg-soft);
  color: var(--sa-fg-muted);
  font: inherit;
  font-size: 11.5px;
  padding: 5px 12px;
  cursor: pointer;
}
.sa-kb-tab-active {
  background: var(--sa-bg);
  color: var(--sa-fg);
  font-weight: 600;
}
.sa-kb-quota {
  margin-left: auto;
  font-size: 11px;
  color: var(--sa-fg-muted);
}
.sa-kb-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--sa-fg-soft);
  margin: 6px 0;
  cursor: pointer;
}
.sa-kb-check input { accent-color: var(--sa-accent); }
.sa-kb-source {
  border: 1px solid var(--sa-border);
  border-radius: 999px;
  background: var(--sa-bg-soft);
  color: var(--sa-fg-muted);
  font-size: 10.5px;
  line-height: 16px;
  padding: 0 7px;
  margin-left: 6px;
}
.sa-kb-source-manual {
  border-color: var(--sa-primary-border);
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
}
.sa-think {
  border: 1px dashed var(--sa-border);
  border-radius: 10px;
  background: var(--sa-bg-soft);
  margin-bottom: 8px;
  font-size: 11.5px;
  color: var(--sa-fg-soft);
}
.sa-think > summary {
  cursor: pointer;
  padding: 6px 10px;
  list-style: none;
  color: var(--sa-fg-muted);
  user-select: none;
}
.sa-think > summary::-webkit-details-marker { display: none; }
.sa-think > summary::before { content: "▸ "; }
.sa-think[open] > summary::before { content: "▾ "; }
.sa-think-running { color: var(--sa-fg-muted); }
.sa-think-body {
  padding: 6px 10px 8px;
  border-top: 1px dashed var(--sa-border);
  white-space: pre-wrap;
  line-height: 1.5;
  max-height: 240px;
  overflow: auto;
}
.sa-steps {
  border: 1px solid var(--sa-border);
  border-radius: 10px;
  background: var(--sa-bg-soft);
  margin-bottom: 8px;
  overflow: hidden;
}
.sa-steps-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--sa-fg-soft);
  font-size: 11.5px;
  font-family: inherit;
  cursor: pointer;
  text-align: left;
}
.sa-steps-head:hover { background: var(--sa-bg-hover); }
.sa-steps-label { font-weight: 600; }
.sa-steps-fail {
  color: var(--sa-danger);
  background: var(--sa-danger-soft);
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 10.5px;
}
.sa-steps-running {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-steps-caret {
  margin-left: auto;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-steps-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 8px 8px;
  border-top: 1px solid var(--sa-border);
}
.sa-steps-body .sa-tool {
  background: var(--sa-bg);
  border-color: transparent;
  box-shadow: none;
}
.sa-tool-note {
  padding: 6px 10px;
  font-size: 11px;
  color: var(--sa-fg-muted);
}
.sa-tool-list {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--sa-fg-soft);
}
.sa-tool-list li { margin: 4px 0; }
.sa-tool-list .sa-tool-note { padding: 2px 0; white-space: pre-wrap; }
.sa-highlights {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}
.sa-kb-refs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}
.sa-kb-ref-label {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-kb-ref-chip {
  border: 1px solid var(--sa-border-strong);
  border-radius: 999px;
  padding: 1px 9px;
  font-size: 11px;
  line-height: 1.7;
  cursor: pointer;
  background: var(--sa-bg);
  color: var(--sa-fg-soft);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-kb-ref-chip:hover {
  border-color: var(--sa-accent);
  color: var(--sa-accent);
  background: var(--sa-accent-soft);
}
.sa-kb-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.55);
}
.sa-kb-modal {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(640px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  overflow: auto;
  padding: 14px 16px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-panel);
  background: var(--sa-bg);
  box-shadow: var(--sa-shadow);
}
.sa-kb-modal-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.sa-kb-modal-title {
  flex: 1 1 auto;
  font-size: 13px;
  line-height: 1.5;
  color: var(--sa-fg);
}
.sa-kb-modal-close {
  border: 0;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: transparent;
  color: var(--sa-fg-soft);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  flex: 0 0 auto;
}
.sa-kb-modal-close:hover {
  background: var(--sa-bg-hover);
  color: var(--sa-fg);
}
.sa-kb-modal-meta {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-kb-modal-body {
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--sa-fg);
  white-space: pre-wrap;
  word-break: break-word;
  border-top: 1px solid var(--sa-border);
  padding-top: 8px;
}
.sa-kb-modal-note {
  margin-top: 6px;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-chart-block {
  margin: 0;
  padding: 8px 10px 6px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  background: var(--sa-bg);
}
.sa-chart-block .sa-chart { margin: 0; }
.sa-chart-caption {
  margin-top: 2px;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  text-align: left;
}
.sa-chart-detail {
  display: block;
  margin: 3px 0 0;
  padding: 2px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--sa-fg-muted);
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
}
.sa-chart-detail:hover { background: var(--sa-bg-hover); color: var(--sa-fg); }
.sa-chart-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 3px;
}
.sa-chart-actions .sa-chart-detail { margin-top: 0; }
.sa-chart-open {
  padding: 2px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--sa-accent);
  font: inherit;
  font-size: 10.5px;
  cursor: pointer;
  white-space: nowrap;
}
.sa-chart-open:hover { background: var(--sa-bg-hover); }
.sa-chart-raw {
  margin-top: 6px;
  max-height: 240px;
  overflow: auto;
  border: 1px solid var(--sa-border);
  border-radius: 8px;
}
.sa-chart-raw table {
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  font-size: 11px;
}
.sa-chart-raw th,
.sa-chart-raw td {
  border-bottom: 1px solid var(--sa-border);
  padding: 4px 8px;
  text-align: left;
  white-space: nowrap;
}
/* 吸顶表头必须是不透明底色（--sa-bg-soft 在 Superset 主题里是半透明，会透出下方文字） */
.sa-chart-raw th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--sa-bg);
  box-shadow: inset 0 -1px 0 var(--sa-border);
}

.sa-chart-canvas { min-width: 0; }
.sa-chart-multi { display: grid; gap: 10px; align-items: start; }
.sa-kpi-grid { display: grid; gap: 8px; align-items: stretch; }
.sa-kpi-card {
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--sa-border);
  border-radius: 8px;
  background: var(--sa-bg-soft);
}
.sa-kpi-label {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-kpi-value {
  margin-top: 2px;
  font-size: 20px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--sa-fg);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-kpi-hint {
  margin-top: 2px;
  font-size: 10px;
  color: var(--sa-fg-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-chart-metric {
  font-size: 10.5px;
  font-weight: 500;
  color: var(--sa-fg-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sa-chart-wrap.is-clickable { cursor: zoom-in; border-radius: 6px; }
.sa-chart-wrap.is-clickable:focus-visible { outline: 2px solid var(--sa-primary-border); outline-offset: 2px; }
.sa-chart-zoom-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.55);
}
.sa-chart-zoom {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: min(1280px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  overflow: auto;
  padding: 16px 18px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-panel);
  background: var(--sa-bg);
  box-shadow: var(--sa-shadow);
}
.sa-chart-zoom-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sa-chart-zoom-head .sa-chart-caption { flex: 1 1 auto; text-align: left; }
.sa-chart-zoom-close {
  border: 0;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: transparent;
  color: var(--sa-fg-soft);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  flex: 0 0 auto;
}
.sa-chart-zoom-close:hover { background: var(--sa-bg-hover); color: var(--sa-fg); }
.sa-chart-zoom .sa-chart-raw { max-height: 40vh; }

.sa-chart-raw-note {
  padding: 4px 8px;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
}
.sa-tool {
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg-soft);
  overflow: hidden;
  transition: border-color 0.15s ease;
}
.sa-tool:hover { border-color: var(--sa-border-strong); }
.sa-tool-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  cursor: pointer;
  user-select: none;
}
.sa-tool-head:hover { background: var(--sa-bg-hover); }
.sa-tool-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--sa-fg);
}
.sa-tool-summary {
  font-size: 11px;
  color: var(--sa-fg-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-tool-state {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
}
.sa-tool-body {
  border-top: 1px solid var(--sa-border);
  padding: 9px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sa-tool-error {
  color: var(--sa-danger);
  background: var(--sa-danger-soft);
  border-radius: var(--sa-radius);
  padding: 7px 9px;
  font-size: 11.5px;
}
.sa-warning {
  color: var(--sa-warn);
  background: var(--sa-warn-soft);
  border-radius: var(--sa-radius);
  padding: 6px 8px;
  font-size: 11px;
}

.sa-write {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg);
}
.sa-write-top {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sa-write-risk {
  padding: 1px 7px;
  border: 1px solid var(--sa-border-strong);
  border-radius: 999px;
  font-size: 10px;
  color: var(--sa-fg-soft);
  background: var(--sa-bg-soft);
}
.sa-write-risk-medium {
  border-color: var(--sa-warn);
  color: var(--sa-warn);
  background: var(--sa-warn-soft);
}
.sa-write-risk-high {
  border-color: var(--sa-danger);
  color: var(--sa-danger);
  background: var(--sa-danger-soft);
}
.sa-write-status {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-write-summary {
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--sa-fg);
}
.sa-write-meta,
.sa-write-expiry {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  word-break: break-word;
}
.sa-write-plan summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--sa-fg-soft);
}
.sa-write-plan pre {
  margin-top: 6px;
}
.sa-write-result-line {
  font-size: 11px;
  color: var(--sa-fg-soft);
  margin: 2px 0;
}
.sa-write-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 2px;
}
.sa-write-primary,
.sa-write-secondary,
.sa-write-danger,
.sa-write-batch {
  border: 1px solid var(--sa-border-strong);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
  background: var(--sa-bg);
  color: var(--sa-fg-soft);
}
.sa-write-primary {
  border-color: var(--sa-accent);
  background: var(--sa-accent);
  color: var(--sa-on-accent);
}
.sa-write-danger {
  border-color: var(--sa-danger);
  background: var(--sa-danger);
  color: var(--sa-on-accent);
}
.sa-write-batch {
  border-style: dashed;
  border-color: var(--sa-accent);
  background: transparent;
  color: var(--sa-accent);
}
.sa-write-bulk {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px 10px;
  border: 1px solid var(--sa-warn);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-warn-soft);
}
.sa-write-bulk-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--sa-fg);
}
.sa-write-bulk-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 0;
  padding-left: 18px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--sa-fg-soft);
}
.sa-write-bulk-list em {
  margin-left: 6px;
  font-style: normal;
  font-size: 10px;
  color: var(--sa-warn);
}
.sa-write-bulk-note {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-write-primary:disabled,
.sa-write-secondary:disabled,
.sa-write-danger:disabled,
.sa-write-batch:disabled {
  opacity: 0.5;
  cursor: default;
}
.sa-badges { display: flex; flex-wrap: wrap; gap: 5px; }
.sa-badge {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--sa-border);
  background: var(--sa-bg);
  color: var(--sa-fg-soft);
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 10.5px;
}
.sa-badge-accent {
  border-color: var(--sa-accent);
  color: var(--sa-accent);
  background: var(--sa-accent-soft);
}

.sa-table-wrap {
  max-height: 280px;
  overflow: auto;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  background: var(--sa-bg);
}
.sa-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
  white-space: nowrap;
}
.sa-table th, .sa-table td {
  border-bottom: 1px solid var(--sa-border);
  padding: 4px 7px;
  text-align: left;
}
.sa-table th {
  position: sticky;
  top: 0;
  background: var(--sa-bg-soft);
  font-weight: 600;
  z-index: 1;
}
.sa-table tr:last-child td { border-bottom: 0; }
.sa-table td.sa-num { text-align: right; font-variant-numeric: tabular-nums; }
.sa-table-more {
  padding: 5px 7px;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-stat-notes > summary {
  cursor: pointer;
  color: var(--sa-fg-soft);
  user-select: none;
}
.sa-stat-notes[open] > summary { margin-bottom: 5px; }
.sa-stat-line {
  padding: 2px 0;
  line-height: 1.6;
  color: var(--sa-fg-soft);
  overflow-wrap: anywhere;
}
.sa-stat-caveat {
  margin-top: 3px;
  padding-left: 7px;
  border-left: 2px solid var(--sa-border-strong);
  color: var(--sa-fg-muted);
}
.sa-stat-notes .sa-table-wrap { margin: 3px 0; }

.sa-forecast-area {
  fill: var(--sa-accent);
  opacity: 0.16;
  stroke: none;
}
.sa-forecast-past, .sa-forecast-future {
  fill: none;
  stroke: var(--sa-accent);
  stroke-width: 1.6;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.sa-forecast-future { stroke-dasharray: 4 3; }
.sa-forecast-split {
  stroke: var(--sa-border-strong);
  stroke-width: 1;
  stroke-dasharray: 2 3;
}
.sa-chart-legend-item i.sa-forecast-dash {
  height: 3px;
  border-radius: 0;
  background: linear-gradient(
    to right,
    var(--sa-accent) 0 4px,
    transparent 4px 7px
  );
}
.sa-chart-legend-item i.sa-forecast-band {
  background: var(--sa-accent);
  opacity: 0.3;
}

.sa-sql {
  position: relative;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: var(--sa-radius-lg);
  padding: 10px 34px 10px 12px;
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.sa-copy {
  position: absolute;
  top: 6px;
  right: 6px;
  border: 1px solid rgba(226, 232, 240, 0.25);
  background: rgba(15, 23, 42, 0.7);
  color: #e2e8f0;
  border-radius: 5px;
  font-size: 10px;
  padding: 2px 6px;
  cursor: pointer;
}
.sa-copy:hover { background: rgba(15, 23, 42, 0.95); }

.sa-chart-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.sa-chart {
  display: block;
  width: 100%;
  height: auto;
  max-width: 100%;
  margin: 0;
  font-family: var(--sa-font);
}
.sa-chart-legend-row {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 12px;
  font-size: 10.5px;
  color: var(--sa-fg-soft);
}
.sa-chart-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 46%;
}
.sa-chart-legend-pie .sa-chart-legend-item {
  max-width: 100%;
}
.sa-chart-legend-item i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: 0 0 auto;
}
.sa-chart-legend-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-chart-legend-val {
  color: var(--sa-fg-muted);
  white-space: nowrap;
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}
.sa-chart-grid { stroke: var(--sa-border); stroke-width: 1; opacity: 0.7; }
.sa-chart-axis { stroke: var(--sa-border-strong); stroke-width: 1; }
.sa-chart-tick {
  fill: var(--sa-fg-muted);
  font-size: 9.5px;
}
.sa-chart-value {
  fill: var(--sa-fg-soft);
  font-size: 8.5px;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}
.sa-chart-center {
  fill: var(--sa-fg);
  font-size: 12px;
  font-weight: 600;
}
.sa-bars { display: flex; flex-direction: column; gap: 6px; }
.sa-bar-row {
  display: grid;
  grid-template-columns: 88px 1fr 76px;
  align-items: center;
  gap: 7px;
  font-size: 11px;
}
.sa-bar-label {
  color: var(--sa-fg-soft);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-bar-track {
  height: 8px;
  background: var(--sa-bg-hover);
  border-radius: 999px;
  overflow: hidden;
}
.sa-bar-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--sa-accent);
}
.sa-bar-fill.sa-neg { background: var(--sa-danger); }
.sa-bar-fill.sa-pos { background: var(--sa-success); }
.sa-bar-value {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--sa-fg-soft);
}

.sa-feedback {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 0;
  font-size: 10px;
  color: var(--sa-fg-muted);
}
.sa-feedback-inline {
  margin-top: 6px;
  padding: 0;
}
.sa-feedback-label { margin-right: 2px; }

/* 每条回答下的操作条：点赞/点踩图标 + 复制 */
.sa-msg-actions-row {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 6px;
}
.sa-action-icon {
  width: 24px;
  height: 24px;
  border: 0;
  background: transparent;
  color: var(--sa-fg-muted);
  border-radius: 6px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}
.sa-action-icon:hover {
  background: var(--sa-bg-hover);
  color: var(--sa-fg);
}
.sa-action-icon:disabled {
  opacity: 0.5;
  cursor: default;
}
.sa-action-icon.sa-on-up {
  color: var(--sa-success);
}
.sa-action-icon.sa-on-down {
  color: #ef4444;
}
.sa-action-icon.sa-on-up:hover,
.sa-action-icon.sa-on-down:hover {
  background: var(--sa-bg-hover);
}

/* 回答后的上下文追问推荐 */
.sa-followups {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}
.sa-followups-label {
  font-size: 10px;
  color: var(--sa-fg-muted);
}
.sa-suggestion-mini {
  font-size: 11px;
  padding: 3px 9px;
}

/* 期间对比表涨跌配色 */
.sa-delta-pos { color: var(--sa-success); }
.sa-delta-neg { color: #ef4444; }

/* 结构效应瀑布图 */
.sa-waterfall {
  display: flex;
  gap: 6px;
  align-items: stretch;
  padding: 6px 2px 2px;
}
.sa-wf-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.sa-wf-plot {
  position: relative;
  width: 100%;
  height: 104px;
}
.sa-wf-bar {
  position: absolute;
  left: 22%;
  right: 22%;
  border-radius: 3px;
  min-height: 2px;
}
.sa-wf-bar-pos { background: var(--sa-success, #22c55e); }
.sa-wf-bar-neg { background: #ef4444; }
.sa-wf-bar-total {
  left: 30%;
  right: 30%;
  background: var(--sa-accent);
  opacity: 0.85;
}
.sa-wf-zero {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px dashed var(--sa-border-strong);
}
.sa-wf-label {
  font-size: 10px;
  color: var(--sa-fg-muted);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.sa-wf-val {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: var(--sa-fg-soft);
}
.sa-feedback-btn {
  border: 1px solid var(--sa-border);
  background: var(--sa-bg);
  color: var(--sa-fg-soft);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 10px;
  cursor: pointer;
}
.sa-feedback-btn:hover {
  border-color: var(--sa-primary-border);
  color: var(--sa-fg);
}
.sa-feedback-btn-active {
  border-color: var(--sa-accent);
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
}
.sa-feedback-btn:disabled { opacity: 0.6; cursor: default; }
.sa-feedback-done { color: var(--sa-success); }

.sa-pick-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  align-self: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 1px solid var(--sa-border);
  border-radius: 999px;
  background: transparent;
  color: var(--sa-fg-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.sa-pick-btn:hover:not(:disabled) { border-color: var(--sa-border-strong); color: var(--sa-fg-soft); }
.sa-pick-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sa-pick-btn-active {
  border-color: var(--sa-primary-border);
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
}
.sa-selection-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 2px 6px;
  max-width: 880px;
  margin: 0 auto;
}
.sa-msg-selection {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-msg-selection-compact { margin-bottom: 2px; }
.sa-msg-user .sa-msg-selection {
  align-self: flex-end;
  justify-content: flex-end;
}
.sa-msg-selection-label { color: var(--sa-fg-muted); }
.sa-msg-selection-chip {
  border: 1px solid var(--sa-border);
  border-radius: 999px;
  padding: 1px 7px;
  background: var(--sa-bg-soft);
  color: var(--sa-fg-soft);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-selection-hint {
  align-self: center;
  color: var(--sa-fg-muted);
  font-size: 10.5px;
  margin-right: 2px;
}
.sa-selection-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px 2px 7px;
  border: 1px solid var(--sa-primary-border);
  border-radius: 999px;
  background: var(--sa-accent-soft);
  color: var(--sa-fg-soft);
  font-size: 11px;
  max-width: 260px;
}
.sa-selection-kind {
  color: var(--sa-accent);
  flex: 0 0 auto;
}
.sa-selection-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.sa-selection-remove {
  border: 0;
  background: transparent;
  color: var(--sa-fg-muted);
  font-size: 13px;
  line-height: 1;
  padding: 0 2px;
  cursor: pointer;
  flex: 0 0 auto;
}
.sa-selection-remove:hover { color: var(--sa-danger); }
/* 选择态：面板透明且点击穿透，被面板遮住的图表/筛选器也能直接点选。
   提示条挂在 body 上，拿不到 --sa-* 变量，配色与 .sa-block-highlight 一致。 */
.sa-panel.sa-panel-picking {
  opacity: 0.18;
  pointer-events: none;
}
.sa-pick-hud {
  position: fixed;
  top: 14px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2147483200;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 6px 12px;
  border: 1px solid #2893b3;
  border-radius: 999px;
  background: #ffffff;
  color: #1f2933;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 12px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.18);
}
.sa-pick-hud button {
  border: 0;
  border-radius: 999px;
  padding: 3px 11px;
  background: #e8f4f8;
  color: #1b708c;
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.sa-pick-hud button:hover { background: #2893b3; color: #ffffff; }
.sa-block-highlight {
  position: fixed;
  z-index: 2147483000;
  display: none;
  pointer-events: none;
  border: 2px solid #2893b3;
  border-radius: 6px;
  background: rgba(40, 147, 179, 0.08);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}
.sa-block-highlight-label {
  position: absolute;
  left: -2px;
  top: -22px;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 7px;
  border-radius: 4px;
  background: #2893b3;
  color: #fff;
  font-size: 11px;
  line-height: 16px;
}
.sa-composer {
  flex: 0 0 auto;
  border-top: 1px solid var(--sa-border);
  padding: 10px 12px 11px;
  background: var(--sa-bg);
}
.sa-composer-box {
  max-width: 880px;
  margin: 0 auto;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg-soft);
  padding: 4px 8px 2px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.sa-composer-box:focus-within {
  border-color: var(--sa-primary-border);
  box-shadow: 0 0 0 3px var(--sa-accent-soft);
}
/* 正文与工具行之间的虚线分隔；发送按钮靠最右 */
.sa-composer-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  min-height: 36px;
  margin-top: 6px;
  padding-top: 2px;
  border-top: 1px dashed var(--sa-border-strong);
}
.sa-composer-bar .sa-send {
  margin-left: auto;
}
/* 员工与模型胶囊按内容撑开、文字完整显示；放不下时整项换行 */
.sa-composer-bar .sa-employee-picker { flex: 0 0 auto; max-width: 100%; }
.sa-composer-bar .sa-model-picker { flex: 0 0 auto; min-width: 0; max-width: 100%; }
.sa-composer-bar .sa-model-badge { display: none; }
.sa-composer-bar .sa-reasoning-picker { flex: 0 1 auto; min-width: 46px; max-width: 72px; }
.sa-composer-bar .sa-reasoning-prefix { display: none; }
/* 选择器移到输入区后，下拉必须朝上；菜单改成相对整条工具行定位，
   宽度等于行宽，窄面板里不会溢出面板左右缘 */
.sa-composer-bar {
  position: relative;
}
.sa-composer-bar .sa-model-picker,
.sa-composer-bar .sa-employee-picker,
.sa-composer-bar .sa-reasoning-picker {
  position: static;
}
.sa-composer-bar .sa-model-menu,
.sa-composer-bar .sa-employee-menu {
  top: auto;
  bottom: calc(100% + 6px);
  left: 0;
  right: auto;
  width: max-content;
  max-width: 100%;
  max-height: 268px;
}
.sa-textarea {
  display: block;
  width: 100%;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: var(--sa-fg);
  font: inherit;
  font-size: 12.5px;
  line-height: 1.5;
  height: 50px;
  max-height: 50px;
  min-height: 50px;
  overflow-y: auto;
  padding: 2px 0;
}
.sa-textarea::placeholder { color: var(--sa-fg-muted); }
.sa-send {
  border: 0;
  border-radius: 9px;
  background: var(--sa-accent);
  color: var(--sa-on-accent);
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex: 0 0 auto;
  transition: filter 0.15s ease, transform 0.15s ease;
}
.sa-send:hover { filter: brightness(1.06); transform: translateY(-1px); }
.sa-send:disabled { opacity: 0.45; cursor: default; }
.sa-send.sa-stop { background: var(--sa-danger); }
.sa-hint {
  max-width: 880px;
  margin: 6px auto 0;
  font-size: 10px;
  color: var(--sa-fg-muted);
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.sa-error {
  margin: 0 12px 10px;
  border: 1px solid var(--sa-danger);
  background: var(--sa-danger-soft);
  color: var(--sa-danger);
  border-radius: var(--sa-radius);
  padding: 7px 9px;
  font-size: 11.5px;
}
.sa-spinner {
  display: inline-block;
  width: 11px;
  height: 11px;
  border: 2px solid var(--sa-border);
  border-top-color: var(--sa-accent);
  border-radius: 50%;
  animation: sa-spin 0.8s linear infinite;
  vertical-align: -1px;
}
@keyframes sa-spin { to { transform: rotate(360deg); } }

.sa-thinking {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--sa-fg-muted);
  font-size: 11.5px;
  padding: 2px 0;
}

.sa-notice {
  flex: 0 0 auto;
  padding: 6px 12px;
  border-bottom: 1px solid var(--sa-border);
  background: var(--sa-accent-soft);
  color: var(--sa-accent);
  font-size: 11px;
}

.sa-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  width: 16px;
  height: 16px;
  cursor: nwse-resize;
  touch-action: none;
  z-index: 8;
}

.sa-history {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-bg);
}
.sa-history-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--sa-border);
  font-size: 12px;
}
.sa-history-head strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.sa-history-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 25px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
/* 关面板后重开的「后台生成中」续看 */
.sa-resume {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--sa-bg);
}
.sa-resume-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--sa-border);
  font-size: 12px;
}
.sa-resume-hint {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--sa-fg-muted);
  font-size: 11px;
}
.sa-resume-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sa-resume-label {
  color: var(--sa-fg-muted);
  font-size: 11px;
}
.sa-resume-q {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
}
.sa-resume-q-text {
  max-width: 86%;
  padding: 9px 13px;
  border-radius: 14px 14px 4px 14px;
  background: var(--sa-accent);
  color: var(--sa-on-accent);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
}
.sa-resume-a {
  flex: 1 1 auto;
  padding: 10px 12px;
  border: 1px solid var(--sa-border-strong);
  border-radius: var(--sa-radius-lg);
  background: var(--sa-bg-soft);
  color: var(--sa-fg);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.sa-resume-meta {
  color: var(--sa-fg-muted);
  font-size: 11px;
}
.sa-resume-stop {
  flex: 0 0 auto;
}
.sa-history-body-detail {
  padding-top: 0;
}
/* 详情页的会话元信息与操作按钮固定在顶部，滚动记录时不跟着滚走 */
.sa-history-subhead {
  position: sticky;
  top: 0;
  z-index: 4;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 9px 0 8px;
  background: var(--sa-bg);
  box-shadow: 0 1px 0 var(--sa-border);
}
.sa-history-empty {
  color: var(--sa-fg-muted);
  font-size: 11.5px;
  padding: 18px 6px;
  text-align: center;
}
.sa-history-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sa-history-item {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  background: var(--sa-bg-soft);
  padding: 8px 9px;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.sa-history-item:hover { border-color: var(--sa-border-strong); }
.sa-history-item-active {
  border-color: var(--sa-accent);
  background: var(--sa-accent-soft);
}
.sa-history-open {
  flex: 1 1 auto;
  min-width: 0;
  text-align: left;
  border: 0;
  background: transparent;
  color: var(--sa-fg);
  padding: 0;
  cursor: pointer;
  font: inherit;
}
.sa-history-title {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sa-history-sub {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
  margin-top: 2px;
}
.sa-history-btn,
.sa-history-primary,
.sa-history-danger {
  border: 1px solid var(--sa-border);
  background: var(--sa-bg);
  color: var(--sa-fg-soft);
  border-radius: 8px;
  padding: 3px 9px;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.sa-history-btn:hover {
  background: var(--sa-bg-hover);
  color: var(--sa-fg);
}
.sa-history-primary,
.sa-history-primary:hover {
  border-color: var(--sa-accent);
  background: var(--sa-accent);
  color: var(--sa-on-accent);
}
.sa-history-primary:hover { filter: brightness(1.06); }
.sa-history-danger,
.sa-history-danger:hover {
  border-color: var(--sa-danger);
  background: var(--sa-danger);
  color: var(--sa-on-accent);
}
.sa-history-danger:hover { filter: brightness(1.06); }
.sa-history-delete {
  color: var(--sa-danger);
}
.sa-history-confirm {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.sa-history-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}
.sa-history-meta {
  font-size: 10.5px;
  color: var(--sa-fg-muted);
}
.sa-history-messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sa-history-msg {
  border-bottom: 1px solid var(--sa-border);
  padding-bottom: 9px;
}
.sa-history-msg:last-child {
  border-bottom: 0;
}
.sa-history-msg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10px;
  color: var(--sa-fg-muted);
  margin-bottom: 4px;
}
.sa-history-role {
  font-weight: 600;
  color: var(--sa-fg-soft);
}
.sa-history-role-user {
  color: var(--sa-accent);
}
.sa-history-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.55;
}
.sa-history-tools {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sa-history-tools-title {
  font-size: 11.5px;
  font-weight: 600;
  margin-top: 4px;
}
.sa-history-tool {
  border: 1px solid var(--sa-border);
  border-radius: var(--sa-radius);
  background: var(--sa-bg-soft);
  padding: 6px 9px;
}
.sa-history-tool summary {
  cursor: pointer;
  font-size: 11px;
  color: var(--sa-fg-soft);
}
.sa-history-label {
  margin-top: 6px;
  margin-bottom: 2px;
  font-size: 10px;
  color: var(--sa-fg-muted);
}
.sa-history-json {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: var(--sa-radius);
  padding: 8px 9px;
  font-size: 10px;
  overflow: auto;
  max-height: 220px;
  white-space: pre-wrap;
  word-break: break-word;
}

.sa-panel ::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.sa-panel ::-webkit-scrollbar-track { background: transparent; }
.sa-panel ::-webkit-scrollbar-thumb {
  background: var(--sa-border-strong);
  border-radius: 999px;
}
.sa-panel ::-webkit-scrollbar-thumb:hover {
  background: var(--sa-fg-muted);
}

@media (prefers-reduced-motion: reduce) {
  .sa-trigger,
  .sa-suggestion,
  .sa-send,
  .sa-tool,
  .sa-history-item {
    transition: none;
  }
}
`;

export function injectStyles(): void {
  if (document.getElementById("sa-assistant-styles")) {
    return;
  }
  const style = document.createElement("style");
  style.id = "sa-assistant-styles";
  style.textContent = CSS;
  document.head.appendChild(style);
}
