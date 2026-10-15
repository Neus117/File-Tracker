"""pytest 配置：把 ``src/`` 放进导入路径。

``src/File Tracker_v1.1.py`` 那个文件名**带空格，不可能被 import**——
原来的 ``tests/test_file_tracker.py`` 写的是 ``from src.file_tracker import MainWindow``，
两个名字都不存在。现在源码在 ``src/file_tracker/`` 这个正规包里，
这里只负责把它找出来。
"""

from __future__ import annotations

import os
import sys

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def _deterministic_language():
    """**每条测试都在同一个语言下跑。**

    ## 为什么必须有这个

    CI 从 v1.2.3 起**每次推送都失败**，而本地全绿。原因就是这个：

    ```python
    # tests/test_tree_nav.py
    assert "不存在" in plan["hint"]
    ```

    `build_walk_plan` 的 hint 是 ``L(f"路径不存在：{text}", f"Path not found: {text}")``
    —— **跟着界面语言走**。GitHub Actions 的 runner 是**英文系统**，
    于是那条断言拿到 `'Path not found: ...'` 就挂了。

    本地是中文系统，这句 `L()` 永远走中文分支，**所以我从来没见过它失败**。

    ## 为什么修在这里而不是只改那一条

    "测试结果取决于跑测试那台机器的语言"是个**系统性**的毛病：
    今天挂的是这一条，明天加一条新的断言就会再挂一次。
    在 `conftest.py` 里统一定死，是让整套测试与语言无关的**唯一**做法。

    为什么钉中文：这些测试断言的本来就是中文文案（`'频次'`、`'中文'`，
    以及 `SORT_SPECS` 的 `chinese` 字段）。钉成英文要改一批断言，
    而那些断言验的是**真实存在的中文文案**，不该为了环境而改。

    **英文那一侧也在测**，而且是显式地测：见
    `test_tree_nav.py::test_hint_follows_language` ——它把两种语言都验一遍。

    用 `try/finally` 还原：某条测试中途抛异常时，后面的测试不该继承
    一个被改过的语言。

    还原的是**系统检测出来的那个值**，不是"我进来时看到的值"——
    后者会被上一条测试留下的状态污染（模块级 `_chinese` 是全局的）。
    """
    from file_tracker import lang

    lang.apply(None)                      # 回到"跟随系统"
    system_default = lang._chinese
    lang.apply(lang.PREFERENCE_CHINESE)
    try:
        yield
    finally:
        lang._chinese = system_default
