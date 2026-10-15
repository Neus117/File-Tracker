"""配置读写：``%APPDATA%\\File Tracker\\config.json``。

旧代码把配置读写散在 ``load_last_directory`` / ``save_last_directory`` /
``save_scroll_position`` / ``restore_scroll_position`` 四处，每处各写一遍
``try/except (FileNotFoundError, json.JSONDecodeError)``。

**还有一个真实的缺陷**：``save_last_directory`` 与 ``save_scroll_position``
各自 ``open(..., 'w')`` 整个文件。前者写 ``{'last_directory': ...}``，
后者先读再改再写——但只有后者读。于是"先保存目录、再保存滚动位置"是安全的，
反过来就会把 ``last_directory`` 整个抹掉。**这里改成一次读、一次写。**
"""

from __future__ import annotations

import json
import os

from .lang import PREFERENCE_CHINESE, PREFERENCE_ENGLISH

DEFAULT_DIRECTORY = "C:\\"

#: 语言键的合法取值，**从 `lang` 取**——不在这里另抄一份字面量，
#: 否则两边迟早不一致（那正是本项目修过的"两份实现"类缺陷）。
LANGUAGES = (PREFERENCE_CHINESE, PREFERENCE_ENGLISH)


class Config:
    """配置文件的读写封装。文件不存在或损坏时回退到默认值。"""

    def __init__(self, config_file: str):
        self.config_file = config_file
        self._data: dict = {}
        self.load()

    def load(self) -> dict:
        try:
            with open(self.config_file, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            self._data = loaded if isinstance(loaded, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._data = {}
        return self._data

    def get_last_directory(self) -> str:
        """上次浏览的目录；路径已失效时回退到 ``C:\\``。

        **必须做存在性检查**：配置里可能存着一个已经拔掉的移动盘符，
        直接交给 ``wx.GenericDirCtrl`` 会得到一个空树。
        """
        last_dir = self._data.get("last_directory") or DEFAULT_DIRECTORY
        try:
            return last_dir if os.path.exists(last_dir) else DEFAULT_DIRECTORY
        except (OSError, ValueError):
            return DEFAULT_DIRECTORY

    def set_last_directory(self, directory: str) -> None:
        self._data["last_directory"] = directory

    def get_language(self) -> str | None:
        """界面语言偏好：``"zh"`` / ``"en"``；**没设过就返回 ``None``**。

        ``None`` 与 ``"en"`` 是两件事：前者表示"问系统"，
        后者表示"用户明确选了英文"。中文系统上特意选了英文的人，
        不该每次启动都被切回中文。

        认不出的值一律当成 ``None``（问系统）——配置文件是可以手改的，
        写错一个字符串不该让界面变成空白或崩溃。
        """
        value = self._data.get("language")
        return str(value) if value in LANGUAGES else None

    def set_language(self, preference: str) -> None:
        """写入语言偏好。**只接受已知取值**，其余忽略。"""
        if preference in LANGUAGES:
            self._data["language"] = preference

    def get_scroll_position(self) -> float:
        """目录树的纵向滚动位置，存的是 0..1 的相对值。

        存相对值的意义：树的高度随展开状态变化，绝对像素位置跨次运行没有意义。
        """
        scroll = self._data.get("scroll_position") or {}
        if not isinstance(scroll, dict):
            return 0.0
        try:
            return float(scroll.get("v_relative", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def set_scroll_position(self, v_relative: float) -> None:
        try:
            value = float(v_relative)
        except (TypeError, ValueError):
            value = 0.0
        self._data["scroll_position"] = {"v_relative": max(0.0, min(1.0, value))}

    def save(self) -> None:
        """整份写回。写失败时抛 :class:`OSError`，由调用方决定怎么告诉用户。"""
        directory = os.path.dirname(self.config_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
