"""审计：PYZ 里的模块 vs 应用**真正**用到的模块。

## 判据怎么来的（不靠猜）

1. 扫 `src/file_tracker/*.py` 里所有 `import X` / `from X import`，
   取顶层包名 —— 那是"应用直接要的"。
2. 读产物 PYZ 的模块清单 —— 那是"PyInstaller 实际打进去的"。
3. 差集里，**能用"谁 import 它"解释清楚的不算多余**：
   标准库里一个模块被另一个模块内部导入是正常的
   （例如 `json` 会拉 `re`、`datetime` 会拉 `_strptime`）。
   所以这里额外做一次**传递闭包**：从应用直接导入的模块出发，
   在**本机完整的标准库**上算出"可达模块集合"，与 PYZ 清单比。

   可达集合之外的 = 打进去了但**从应用出发走不到**的 = 真的多余。
   这比"名字看起来像测试框架"这种判断可靠得多。

用法::

    python -X utf8 tools/probes/probe_pyz_contents.py
"""

from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, "src")
from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

SRC = os.path.join("src", "file_tracker")
EXE = os.path.join("dist", "File Tracker.exe")
PYZ_NAME = "PYZ-00.pyz"


def app_imports() -> set[str]:
    """扫源码，取应用**直接**导入的顶层模块名。"""
    found: set[str] = set()
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(SRC, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
    # 打包期注入的那个模块
    found.add("file_tracker")
    return found


def reachable(roots: set[str]) -> set[str]:
    """从这些顶层模块出发，在**本机标准库 + 已装包**上算可达闭包。

    用 `importlib` 真去导入、再看 `sys.modules` 新增了什么——
    比静态分析 `ast` 更准，因为它顺着真实的 C 扩展与 `__init__` 走。
    """
    before = set(sys.modules)
    for name in sorted(roots):
        try:
            __import__(name)
        except Exception:                            # noqa: BLE001
            pass
    return before, set(sys.modules) - before


def pyz_modules() -> tuple[list[str], str]:
    reader = CArchiveReader(EXE)
    path = os.path.join("build", "File-Tracker", PYZ_NAME)
    if not os.path.exists(path):
        os.makedirs(os.path.join("build", "_audit"), exist_ok=True)
        path = os.path.join("build", "_audit", PYZ_NAME)
        with open(path, "wb") as handle:
            handle.write(reader.extract(PYZ_NAME))
    pyz = ZlibArchiveReader(path)
    return sorted(pyz.toc), path


direct = app_imports()
print(f"=== 应用直接导入的顶层模块（{len(direct)} 个）===")
print("  " + " ".join(sorted(direct)))
print()

before, loaded = reachable(direct)
print(f"=== 从这些模块出发，本机可达的新增模块（{len(loaded)} 个）===")
reachable_tops = {name.split(".")[0] for name in loaded} | direct
print("  " + " ".join(sorted(reachable_tops)))
print()

modules, path = pyz_modules()
print(f"=== PYZ 里的模块（{len(modules)} 个，文件 {os.path.getsize(path):,d} B）===")
print("  " + " ".join(modules))
print()

pyz_tops = {name.split(".")[0] for name in modules}
extra = sorted(pyz_tops - reachable_tops)
print(f"=== 打进去但**从应用出发走不到**的顶层模块（{len(extra)} 个）===")
for name in extra:
    submodules = sorted(m for m in modules
                        if m == name or m.startswith(name + "."))
    print(f"    {name:16} （{len(submodules)} 个模块：{', '.join(submodules[:6])}"
          + (" …" if len(submodules) > 6 else "") + "）")
print()
print("  **这些是 `excludes` 的候选。** 但注意：")
print("  * C 扩展在**运行中途**按需导入的，上面这招看不出来——")
print("    所以每一项都要在真机跑一遍再排除，别一次全排。")
print("  * `_pydecimal` / `decimal` 有一个会被 `_strptime` 之类的用到，")
print("    排之前先确认 `datetime` 还能用。")
