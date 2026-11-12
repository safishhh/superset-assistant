from __future__ import annotations

import re

TITLE_MAX_CHARS = 24
_MAX_QUESTION = 200
_MAX_ANSWER = 240

_TRIM_HEAD = " \t\"'“”‘’「」『』《》【】#*`·-—"
_TRIM_TAIL = "。．.!！?？；;，,、：: "
_CJK = re.compile(r"[\u4e00-\u9fff]")
_MARKDOWN_LEFTOVERS = ("**", "__", "`", "##", "- ", "* ")

# 小模型爱给的“正确但没信息量”的标题：命中则改用问题首句兜底
_GENERIC_TITLES = {
    "分析请求",
    "查询请求",
    "数据查询",
    "数据分析",
    "查询结果",
    "数据概览",
    "会话",
    "对话",
    "问题",
    "用户问题",
}

# 小模型有时把指令原文当答案复述出来（实测 MiniCPM 会输出
# “用户要求生成一个不超过16个字的中文会话标题”），这类输出一律判为不可用，
# 保留原来的问题文本当标题。
_ECHO_MARKERS = (
    "不超过",
    "生成一个",
    "会话标题",
    "标题本身",
    "只输出",
    "用户要求",
    "要求生成",
    "中文短语",
    "中文标题",
)


def clean_title(raw: str) -> str:
    """把模型输出裁成一行干净标题：去引号/列表符号/加粗/markdown、“标题：”前缀，限长 24 字。"""
    text = (raw or "").strip()
    if not text:
        return ""
    # 取第一行有内容的文本
    line = next((item for item in text.splitlines() if item.strip()), "")
    text = line.strip()
    for prefix in ("标题：", "标题:", "会话标题：", "会话标题:", "Title:", "title:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^[\s#>*\-–—\d\.\)、]+", "", text)
    text = text.strip(_TRIM_HEAD).rstrip(_TRIM_TAIL).strip()
    return text[:TITLE_MAX_CHARS]


def is_usable_title(title: str) -> bool:
    """标题必须像中文短标题：复述指令、纯英文句子、markdown 残渣、几乎没有汉字的一律判废。"""
    if not title or any(marker in title for marker in _ECHO_MARKERS):
        return False
    if title.strip() in _GENERIC_TITLES:
        return False
    if any(mark in title for mark in _MARKDOWN_LEFTOVERS):
        return False
    if re.search(r"[，。；;：:!?！？]", title):
        return False
    if title[0].isdigit():
        return False
    cjk = len(_CJK.findall(title))
    if cjk < 2:
        return False
    visible = len([char for char in title if not char.isspace()])
    return cjk / max(visible, 1) >= 0.4


def fallback_title(question: str) -> str:
    """模型标题不可用时，用问题首句压一个短语，保证标题稳定可读。"""
    text = (question or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(请|麻烦|帮我|帮忙|能否|可以|我想|想|看看|看一下)+[\s，,]?", "", text)
    text = re.split(r"[，,。；;\n]", text)[0].strip()
    text = text.rstrip("。．.!！?？：: ")
    return text[:20]


def build_title_prompt(question: str, answer: str) -> str:
    # 指令放在内容之后：小模型对“先给要求再给材料”更容易复述要求本身
    return (
        "问题："
        f"{(question or '').strip()[:_MAX_QUESTION]}\n"
        "回答："
        f"{(answer or '').strip()[:_MAX_ANSWER]}\n\n"
        "用一个不超过 12 个字的中文短语概括上面这段问答的主题，"
        "像“区域销售对比”“大客户口径确认”这样。"
        "只输出这个中文短语，不要标点，不要解释，不要用英文。"
    )
