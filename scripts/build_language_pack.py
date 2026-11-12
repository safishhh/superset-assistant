#!/usr/bin/env python3
"""从 Superset 容器内的 zh messages.po 生成前端语言包 messages.json（jed1.x）。

Superset 的 /language_pack/<lang>/ 需要 superset/translations/<lang>/LC_MESSAGES/messages.json，
该文件由前端构建期的 po2json 生成；运行镜像没有这个产物，导致切换中文后前端
拉包 404、界面回退英文。本脚本在容器内用 Babel 把 .po 转成 jed1.x JSON，
写到 infra/translations/zh-LC-messages.json，由 docker-compose 单文件挂载进容器。

用法：python3 scripts/build_language_pack.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "infra" / "translations" / "zh-LC-messages.json"

CONTAINER_SCRIPT = r"""
import json
from babel.messages.pofile import read_po

PO = "/app/superset/translations/zh/LC_MESSAGES/messages.po"
with open(PO, "rb") as f:
    cat = read_po(f, locale="zh")

data = {
    "domain": "superset",
    "locale_data": {
        "superset": {
            "": {
                "domain": "superset",
                "lang": "zh",
                "plural_forms": cat.plural_forms or "nplurals=1; plural=0;",
            }
        }
    },
}
for msg in cat:
    if msg.id is None or msg.id == "":
        continue
    if isinstance(msg.id, tuple):
        key = msg.id[0]
        if isinstance(msg.string, list):
            value = list(msg.string)
        else:
            value = [msg.string if msg.string else msg.id[1]]
    else:
        key = msg.id
        value = [msg.string if msg.string else ""]
    if msg.context:
        key = f"{msg.context}\u0004{key}"
    data["locale_data"]["superset"][key] = value
print(json.dumps(data, ensure_ascii=False))
"""


def main() -> int:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "assistant-superset",
            "/app/.venv/bin/python",
            "-c",
            CONTAINER_SCRIPT,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = result.stdout
    parsed = json.loads(payload)  # 校验合法 JSON
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    entries = len(parsed["locale_data"]["superset"])
    print(f"wrote {OUT} ({entries} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
