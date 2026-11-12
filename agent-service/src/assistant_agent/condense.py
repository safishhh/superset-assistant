"""用户手填知识条目的「AI 精简」：把原文压成一条自包含的知识点。

小模型不可靠（会复述指令、加 markdown 前言），所以清洗后还要校验，
不合格就退回原文保存——宁可长，也不能丢内容。
"""

from __future__ import annotations

import re

CONDENSED_MAX_CHARS = 2000

_ECHO_MARKERS = (
    "以下是",
    "请精简",
    "请帮我",
    "要求",
    "原文如下",
    "总结如下",
    "好的，",
    "当然可以",
    "作为",
)


def build_condense_prompt(title: str, content: str) -> str:
    return (
        "把下面这条知识库条目改写成更精炼的中文表述，要求：\n"
        "1. 只输出改写后的正文，不要标题、不要前后缀、不要解释；\n"
        "2. 保留全部事实：数字、口径、条件、例外、时间范围；\n"
        "3. 不新增原文没有的信息，不改变原意；\n"
        "4. 用一段或简短分点，总长度不超过 800 字。\n\n"
        f"条目标题：{title}\n"
        f"条目原文：\n{content[:6000]}"
    )


def clean_condensed(raw: str, original: str) -> str:
    """清洗并校验模型输出；不合格返回空串，由调用方退回原文。"""
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text).strip()
    text = re.sub(r"^(正文|内容|改写后|精简后)[:：]\s*", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return ""
    if len(text) > len(original.strip()):
        return ""  # 精简不该比原文长
    head = text[:40]
    if any(marker in head for marker in _ECHO_MARKERS):
        return ""
    return text[:CONDENSED_MAX_CHARS]
