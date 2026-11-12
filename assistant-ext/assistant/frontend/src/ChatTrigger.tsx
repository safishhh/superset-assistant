import React, { useEffect, useRef, useState } from "react";
import { chat } from "@apache-superset/core";

import { hasAssistantAccess } from "./api";
import { AssistantAvatar } from "./AssistantAvatar";
import { useAssistantTheme } from "./theme";

type Edge = "left" | "right";
type StoredTrigger = { edge?: unknown; y?: unknown; dimmed?: unknown };

const POS_KEY = "sa-assistant-trigger-pos";
const SIZE = 72;
// 贴边后静止多久自动半隐藏（藏起 1/3）
const HIDE_DELAY_MS = 10_000;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function clampY(value: number, height = window.innerHeight): number {
  return clamp(value, 8, Math.max(8, height - SIZE - 8));
}

function dockX(edge: Edge, width = window.innerWidth): number {
  return edge === "left" ? 0 : width - SIZE;
}

function readStored(): { edge: Edge; y: number; dimmed: boolean } {
  const fallbackY = clampY(window.innerHeight - 18 - SIZE);
  try {
    const raw = window.localStorage.getItem(POS_KEY);
    if (!raw) return { edge: "right", y: fallbackY, dimmed: false };
    const value = JSON.parse(raw) as StoredTrigger;
    return {
      edge: value.edge === "left" ? "left" : "right",
      y: typeof value.y === "number" ? clampY(value.y) : fallbackY,
      dimmed: value.dimmed === true,
    };
  } catch {
    return { edge: "right", y: fallbackY, dimmed: false };
  }
}

export default function ChatTrigger() {
  const stored = useRef(readStored());
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [open, setOpen] = useState(chat.isOpen());
  const [edge, setEdge] = useState<Edge>(stored.current.edge);
  const [y, setY] = useState<number>(stored.current.y);
  // 静止 30s 后置 true，表现为藏一半；鼠标悬停仅临时滑出
  const [dimmed, setDimmed] = useState<boolean>(stored.current.dimmed);
  const [dragging, setDragging] = useState(false);
  const [hovered, setHovered] = useState(false);
  // 视口尺寸参与贴边计算：窗口变化时必须重算 x，否则球会停在旧宽度处
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const hideTimer = useRef<number | null>(null);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    lastX: number;
    lastY: number;
    moved: boolean;
  } | null>(null);
  const suppressClickRef = useRef(false);
  const themeVars = useAssistantTheme();

  const clearHideTimer = () => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  };

  // 停止操作后重新计时：30s 内不动才半隐藏
  const armHideTimer = () => {
    clearHideTimer();
    hideTimer.current = window.setTimeout(() => {
      setDimmed(true);
    }, HIDE_DELAY_MS);
  };

  useEffect(() => {
    let alive = true;
    hasAssistantAccess()
      .then((value) => {
        if (alive) setAllowed(value);
      })
      .catch(() => {
        if (alive) setAllowed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const opened = chat.onDidOpen(() => {
      setOpen(true);
      clearHideTimer();
    });
    const closed = chat.onDidClose(() => {
      setOpen(false);
      setDimmed(false);
      armHideTimer();
    });
    return () => {
      opened.dispose();
      closed.dispose();
      clearHideTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (open) return undefined;
    armHideTimer();
    return clearHideTimer;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    const onResize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const persist = (nextEdge: Edge, nextY: number, nextDimmed: boolean) => {
    try {
      window.localStorage.setItem(
        POS_KEY,
        JSON.stringify({ edge: nextEdge, y: nextY, dimmed: nextDimmed }),
      );
    } catch {
      // Local storage may be unavailable.
    }
  };

  const toggle = () => {
    if (open) chat.close();
    else chat.open();
  };

  const onPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    clearHideTimer();
    setDimmed(false);
    const rect = event.currentTarget.getBoundingClientRect();
    const drag = {
      startX: event.clientX,
      startY: event.clientY,
      originX: rect.left,
      originY: rect.top,
      lastX: rect.left,
      lastY: rect.top,
      moved: false,
    };
    dragRef.current = drag;
    setDragging(true);
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Synthetic or unsupported pointer capture.
    }

    const move = (moveEvent: PointerEvent) => {
      const dx = moveEvent.clientX - drag.startX;
      const dy = moveEvent.clientY - drag.startY;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      drag.moved = true;
      drag.lastX = clamp(drag.originX + dx, 0, window.innerWidth - SIZE);
      drag.lastY = clampY(drag.originY + dy);
      setEdge(drag.lastX + SIZE / 2 < window.innerWidth / 2 ? "left" : "right");
      setY(drag.lastY);
    };

    const stop = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      try {
        if (event.currentTarget.hasPointerCapture(upEvent.pointerId)) {
          event.currentTarget.releasePointerCapture(upEvent.pointerId);
        }
      } catch {
        // Ignore unsupported pointer capture.
      }
      dragRef.current = null;
      setDragging(false);
      if (!drag.moved) {
        armHideTimer();
        return;
      }
      suppressClickRef.current = true;
      window.setTimeout(() => {
        suppressClickRef.current = false;
      }, 500);
      // 松手后永远吸附到较近的一侧边缘，垂直位置保留
      const nextEdge: Edge =
        drag.lastX + SIZE / 2 < window.innerWidth / 2 ? "left" : "right";
      const nextY = clampY(drag.lastY);
      setEdge(nextEdge);
      setY(nextY);
      setDimmed(false);
      persist(nextEdge, nextY, false);
      armHideTimer();
    };

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  };

  if (allowed !== true) {
    return null;
  }
  // 打开面板后隐藏悬浮球
  if (open) {
    return null;
  }

  const style: React.CSSProperties = {
    ...themeVars,
    left: dockX(edge, viewport.width),
    top: clampY(y, viewport.height),
    right: "auto",
    bottom: "auto",
  };

  return (
    <button
      type="button"
      className={[
        "sa-trigger",
        `sa-trigger-${edge}`,
        !dragging && dimmed && !hovered ? "sa-trigger-dim" : "",
        dragging ? "sa-dragging" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={style}
      title="打开数据分析助手（可拖到另一侧边缘）"
      aria-label="打开数据分析助手"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onPointerDown={onPointerDown}
      onClick={(event) => {
        if (suppressClickRef.current) {
          suppressClickRef.current = false;
          event.preventDefault();
          return;
        }
        toggle();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      }}
    >
      <AssistantAvatar className="sa-trigger-avatar" crop="full" />
    </button>
  );
}
