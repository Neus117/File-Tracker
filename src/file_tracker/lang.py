"""界面语言：用户看到的是中文还是英文，以及读取它的那**唯一一个**调用。

## 为什么字符串写在**调用点**，而不是资源文件

照搬 Roboc `src/Roboc.Core/Model/Lang.cs` 的做法，理由也照搬：

    每条用户可见的文案都写成 `Lang.Pick("中文", "English")`，
    **两半都在调用点**。

资源文件意味着：一堆键、一次可能落空的查找、以及"翻译在另一个文件里"。
而**键漏了的失败方式是把键名或空白显示给用户**。
写成两个参数之后，**编译器/语法本身不允许只写一个**——
一条消息不可能只翻译一半，两种语言也不会各自漂移出对方的视野。

（Python 没有编译期检查，但同样的道理成立：`Pick` 强制两个参数，
少写一个是 `TypeError`，而不是运行时静默显示空白。）

## 为什么看显示语言，而不是时区

顺手的捷径是把 UTC+8 当成中文，两边都错：UTC+8 覆盖西澳、新加坡、
马来西亚、菲律宾、伊尔库茨克、蒙古，它们都不想要中文；
而住在东京的中文用户是 UTC+9。

Windows 本来就知道答案：``GetUserDefaultUILanguage`` 返回的是
**用户为自己的界面选的语言**，那正是他期望这个程序说的语言。
"""

from __future__ import annotations

import ctypes
import os
import sys

#: ``LANG_CHINESE`` —— 中文 LANGID 的低字节。
LANGUAGE_CHINESE = 0x04

#: 存进配置里的取值。
PREFERENCE_CHINESE = "zh"
PREFERENCE_ENGLISH = "en"

#: 支持的选项，**按设置界面里的显示顺序**。
CHOICES = (PREFERENCE_CHINESE, PREFERENCE_ENGLISH)

#: 每个选项在设置里显示的名字。
#:
#: **语言名用自己的语言写，不翻译。** 这是通行做法，而且在这里尤其重要：
#: 一个只看得懂英文的人，在中文界面里找 "English" 时，
#: 看到的必须还是 "English"——把它翻成"英文"他就找不到了。
DISPLAY_NAMES = {
    PREFERENCE_CHINESE: "中文",
    PREFERENCE_ENGLISH: "English",
}

_chinese: bool | None = None


def _detect_from_system() -> bool:
    """用户的 Windows 显示语言是不是中文。

    用 ``GetUserDefaultUILanguage`` 而不是 ``GetSystemDefaultUILanguage``：
    前者是用户为自己账户选的语言，可以与装机语言不同——
    而那恰恰是"每用户设置"应该跟随的情况。

    调用失败时**默认英文**：那是读者最不可能完全用不了的语言。
    """
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        # 非 Windows，或者 API 不可用 —— 退回环境变量
        return _detect_from_environment()
    # 只看低字节：这样一条判断同时覆盖简体（0x0804）、繁体（0x0404）、
    # 香港（0x0C04）、新加坡（0x1004）—— 它们只有高字节不同。
    return (int(lang_id) & 0xFF) == LANGUAGE_CHINESE


def _detect_from_environment() -> bool:
    """``GetUserDefaultUILanguage`` 不可用时的兜底（非 Windows / 测试）。"""
    for name in ("LANG", "LC_ALL", "LC_MESSAGES"):
        value = os.environ.get(name, "")
        if value.lower().startswith(("zh", "chinese")):
            return True
    return False


def apply(preference: str | None) -> bool:
    """应用保存下来的偏好；没有偏好就问系统。

    启动时调用一次，**在任何东西被打印之前**。
    设置是每用户的、检测是每机器的，所以保存的值优先：
    在中文系统上特意选了英文的人，不该每次启动都被切回去。

    返回生效后的 ``is_chinese``。
    """
    global _chinese
    if preference == PREFERENCE_CHINESE:
        _chinese = True
    elif preference == PREFERENCE_ENGLISH:
        _chinese = False
    else:
        _chinese = _detect_from_system()
    return _chinese


def preference(chinese: bool) -> str:
    """某个选择应该存进配置的值。"""
    return PREFERENCE_CHINESE if chinese else PREFERENCE_ENGLISH


def is_chinese() -> bool:
    """当前是不是中文。**没调用过 `apply` 时按系统检测。**"""
    global _chinese
    if _chinese is None:
        _chinese = _detect_from_system()
    return _chinese


def pick(chinese: str, english: str) -> str:
    """两种语言并排。**这是写一条消息的唯一方式。**"""
    return chinese if is_chinese() else english


class _Pick:
    """让调用点写成 ``L.PICK`` 那样可读的形式。"""

    def __call__(self, chinese: str, english: str) -> str:
        return pick(chinese, english)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<pick chinese={is_chinese()}>"


#: 调用点统一写 ``L("中文", "English")``。
L = _Pick()

__all__ = [
    "CHOICES",
    "DISPLAY_NAMES",
    "L",
    "LANGUAGE_CHINESE",
    "PREFERENCE_CHINESE",
    "PREFERENCE_ENGLISH",
    "apply",
    "is_chinese",
    "pick",
    "preference",
]
