"""静态检查：**同名方法在同一个类里被定义了两次**。

## 为什么需要这条检查

审计时发现 `FileTracker._remember_sort` 被定义了**两次**，函数体完全一样。
行为上没出错（内容相同），但这是个**安静的陷阱**：

* Python **只用后一个定义**；前一个被覆盖，属于死代码。
* 于是"改前一个"**不会有任何效果**，而且不报错、不警告。
* `app.py` 开头的模块文档就记着同一类教训（`set_icon` /
  `load_last_directory` 各定义两次、后一个静默生效），
  而它**又长出来了一次**。

人工审查看不出来（两份相隔一千多行），但 AST 一眼就能判。

## 检查范围

`src/file_tracker/*.py` 里每个类的方法名。同名的报出来——
除了少数明确合理的重载场景（本项目目前没有），一律按缺陷处理。

用法::

    python -X utf8 tools/check_duplicate_methods.py
"""

from __future__ import annotations

import ast
import os
import sys
from collections import Counter

#: 允许重复的方法名（本项目的合理重载场景）。
#:
#: 目前为空：Python 没有真正的重载，同名就是覆盖。
ALLOWED = frozenset()


def run(root: str) -> list[str]:
    source_dir = os.path.join(root, "src", "file_tracker")
    if not os.path.isdir(source_dir):
        return [f"找不到源码目录: {source_dir}"]

    problems: list[str] = []
    checked_classes = 0
    checked_methods = 0

    for name in sorted(os.listdir(source_dir)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(source_dir, name)
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            checked_classes += 1
            methods = [item for item in node.body
                       if isinstance(item, (ast.FunctionDef,
                                            ast.AsyncFunctionDef))]
            checked_methods += len(methods)
            counts = Counter(item.name for item in methods
                             if item.name not in ALLOWED)
            for method_name, count in sorted(counts.items()):
                if count < 2:
                    continue
                lines = [item.lineno for item in methods
                         if item.name == method_name]
                problems.append(
                    f"{name}:{lines[-1]} 类 {node.name} 里 "
                    f"{method_name!r} 定义了 {count} 次"
                    f"（行 {', '.join(map(str, lines))}）"
                    f"——只有最后一个生效，改前面的不会有任何效果")

    if not checked_classes:
        problems.append("一个类都没找到——检查器没有可检查的对象")
    elif not checked_methods:
        problems.append("一个方法都没找到——检查器没有可检查的对象")
    return problems


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    problems = run(root)
    if problems:
        print("重复方法检查未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("重复方法检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
