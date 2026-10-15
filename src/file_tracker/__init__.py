"""File Tracker —— 记录访问过的文件夹，按频次与最后访问时间排序。

包结构（分层的目的是**让判断可以自动验证**）：

| 模块 | 依赖 wx？ | 职责 |
|---|---|---|
| :mod:`~file_tracker.core` | **否** | 资源路径、路径规范化、窗口尺寸夹取、版本串 |
| :mod:`~file_tracker.store` | **否** | SQLite 读写 |
| :mod:`~file_tracker.config` | **否** | ``config.json`` 读写 |
| :mod:`~file_tracker.tree_nav` | **否** | 目录树的遍历与路径匹配规则 |
| :mod:`~file_tracker.theme` | **否** | 配色与间距数值 |
| :mod:`~file_tracker.win32` | **否** | 原生消息（列对齐、行距、圆角、深色标题栏） |
| :mod:`~file_tracker.widgets` | 是 | 自绘控件 |
| :mod:`~file_tracker.app` | 是 | 主窗口 |

**前六个模块不 import wx**，因此可以在没有桌面会话的环境里测试——
``tests/`` 里有一条测试专门守这条边界。这是本次重构的主要目的：
四项 UI 改动里有两项（窗口尺寸、频次列）的判断逻辑以前埋在窗口类里，
只能靠人眼看。
"""

from .core import APP_NAME, APP_VERSION, version_string

__all__ = ["APP_NAME", "APP_VERSION", "version_string"]
