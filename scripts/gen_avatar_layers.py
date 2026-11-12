"""由 办公奶牛吉祥物插画.svg 生成 AssistantAvatar.tsx 的分层数据。

用法：python3 scripts/gen_avatar_layers.py
"""
import math
import re

SRC = "办公奶牛吉祥物插画.svg"
TARGET = "assistant-ext/assistant/frontend/src/AssistantAvatar.tsx"

ACCENT_X = 700  # 领带/领结子路径（x 中心小于此值）改吃主题色 var(--sa-avatar-accent)
INK = "#200a08"
EYE_WHITE_R = 60
PUPIL_R = 32


def subpaths(d):
    parts = re.split(r"(?=M)", d)
    return [p for p in parts if p.strip().startswith("M")]


def bbox(d):
    nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", d)]
    xs, ys = nums[0::2], nums[1::2]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def main():
    src = open(SRC).read()
    paths = []
    for tag in re.findall(r"<path\b[^>]*>", src):
        d = re.search(r'\bd="([^"]+)"', tag)
        fill = re.search(r'\bfill="([^"]+)"', tag)
        if d and fill:
            paths.append((fill.group(1), d.group(1)))
    assert paths, "no paths parsed"
    layers = []
    for fill, d in paths:
        if fill != "#2e3242":
            layers.append((fill, d))
            continue
        accent, other = [], []
        for sub in subpaths(d):
            box = bbox(sub)
            cx = (box[0] + box[2]) / 2
            (accent if cx < ACCENT_X else other).append(sub)
        if accent:
            layers.append(("var(--sa-avatar-accent, #2e3242)", "".join(accent)))
        if other:
            layers.append((fill, "".join(other)))

    size = sum(len(d) for _, d in layers)
    print(f"layers={len(layers)} pathdata={size/1024:.1f}KB")

    body = "".join(
        '  { fill: "%s", d:\n    "%s" },\n' % (fill, d) for fill, d in layers
    )
    tsx = TEMPLATE.replace("__LAYERS__", body).replace("__INK__", INK)
    tsx = tsx.replace("__EYER__", str(EYE_WHITE_R)).replace("__PUPILR__", str(PUPIL_R))
    open(TARGET, "w").write(tsx)
    print("wrote", TARGET)


TEMPLATE = '''import { useEffect, useRef } from "react";

/**
 * 助手形象：办公奶牛吉祥物（分层矢量，源图 办公奶牛吉祥物插画.svg）。
 * 路径数据由 scripts/gen_avatar_layers.py 生成，改图请改脚本后重跑，不要手改本文件。
 * 深色层是描边与五官底，其余为各块填色；领带填色走 var(--sa-avatar-accent)
 * 因此跟随 Superset 主题换色。两只瞳孔单独成层，由 --sa-eye-x/--sa-eye-y 平移。
 */
type Layer = { fill: string; d: string };

const LAYERS: Layer[] = [
__LAYERS__];

const INK = "__INK__";
/** 眼白圆心（覆盖深色层里的静态瞳孔）与半径 */
const EYES = [
  { cx: 565.5, cy: 270.5 },
  { cx: 729.5, cy: 276.5 },
];
const EYE_R = __EYER__;
const PUPIL_R = __PUPILR__;
/** 瞳孔在眼白内的最大位移（画布单位） */
const TRACK = EYE_R - PUPIL_R - 2;

const CROPS = {
  /** 脸部特写：铺满圆角容器 */
  head: { box: "400 90 430 430", fit: "xMidYMid slice" },
  /** 整机：等比缩放到容器内 */
  full: { box: "340 30 710 830", fit: "xMidYMid meet" },
} as const;

export type AvatarCrop = keyof typeof CROPS;

const tracked = new Set<SVGSVGElement>();
let pointer = { x: 0, y: 0, active: false };
let frame = 0;

function paint() {
  frame = 0;
  tracked.forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (!rect.width) return;
    const dx = pointer.x - (rect.left + rect.width / 2);
    const dy = pointer.y - (rect.top + rect.height / 2);
    const dist = Math.hypot(dx, dy);
    if (!pointer.active || dist < 0.5) {
      el.style.setProperty("--sa-eye-x", "0");
      el.style.setProperty("--sa-eye-y", "0");
      return;
    }
    // 指针离得越近位移越小，避免贴着头像时眼睛乱抖
    const reach = Math.min(1, dist / 80) * TRACK;
    el.style.setProperty("--sa-eye-x", ((dx / dist) * reach).toFixed(2));
    el.style.setProperty("--sa-eye-y", ((dy / dist) * reach).toFixed(2));
  });
}

function onPointerMove(event: PointerEvent) {
  pointer = { x: event.clientX, y: event.clientY, active: true };
  if (!frame) frame = requestAnimationFrame(paint);
}

function track(el: SVGSVGElement) {
  tracked.add(el);
  if (tracked.size === 1) {
    window.addEventListener("pointermove", onPointerMove, { passive: true });
  }
}

function untrack(el: SVGSVGElement) {
  tracked.delete(el);
  if (tracked.size) return;
  if (frame) {
    cancelAnimationFrame(frame);
    frame = 0;
  }
  window.removeEventListener("pointermove", onPointerMove);
}

export function AssistantAvatar({
  crop = "head",
  follow = true,
  className = "",
}: {
  crop?: AvatarCrop;
  /** 关闭后瞳孔固定朝前（列表里的小头像不需要跟随） */
  follow?: boolean;
  className?: string;
}) {
  const ref = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !follow) return undefined;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      return undefined;
    }
    track(el);
    return () => untrack(el);
  }, [follow]);

  return (
    <svg
      ref={ref}
      className={`sa-avatar${className ? ` ${className}` : ""}`}
      viewBox={CROPS[crop].box}
      preserveAspectRatio={CROPS[crop].fit}
      aria-hidden="true"
      focusable="false"
    >
      {LAYERS.map((layer, index) => (
        // var() 在 SVG 呈现属性里不生效，必须走 style
        <path key={index} d={layer.d} style={{ fill: layer.fill }} />
      ))}
      <g fill="#fdfdfd">
        {EYES.map((eye) => (
          <circle key={`w-${eye.cx}`} cx={eye.cx} cy={eye.cy} r={EYE_R} />
        ))}
      </g>
      <g fill={INK}>
        {EYES.map((eye) => (
          <circle
            key={`p-${eye.cx}`}
            className="sa-avatar-pupil"
            cx={eye.cx}
            cy={eye.cy}
            r={PUPIL_R}
            style={{
              transform:
                "translate(calc(var(--sa-eye-x, 0) * 1px), calc(var(--sa-eye-y, 0) * 1px))",
            }}
          />
        ))}
      </g>
    </svg>
  );
}

export default AssistantAvatar;
'''


main() if __name__ == "__main__" else None
