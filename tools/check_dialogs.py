"""静态检查：每一个 `ThemedDialog` 调用点，**要么只给一个按钮，
要么真的读它的回答**。

## 为什么需要这条检查

用户报的："失效删除确认弹窗有两个按钮，功能完全一致——关闭窗口，
请简化为一个按钮「确定」。"

那个弹窗是 `remove_invalid_path` 里直接建的默认 `ThemedDialog`：
带上「好 / 否(N)」两个按钮，而**两个都只是关掉它**。
一条"已经做完了"的告知被渲染成一个问题，用户会以为还有得选。

这类缺陷**静态就能查出来**：
``yes_label``/``no_label`` 给了两个按钮，而 `ShowModal()` 的返回值
没被比较过 → 两个按钮必然等价。

## 反过来也要查

只给一个按钮（``no_label=None``）却去比较返回值，同样是错的：
那个分支永远走不到——一个**永远不成立的条件**比没有条件更糟，
它看起来像做过处理。

## 用法

    python tools/check_dialogs.py
"""

from __future__ import annotations

import ast
import os
import sys

def _is_none(node) -> bool:
    """**只认 ``None`` 字面量。**

    踩过：早先写成 ``node.value in (None,)``，而
    ``isinstance(ast.Constant('dialog').value, ...)`` 那种比较会把
    **任何字符串**都算进来——于是 ``if __name__ == "__main__":``
    里的 ``'__main__'`` 被当成了 ``no_label`` 的值，检查器对着
    `__main__` 里的对话框报了一堆假错。
    """
    return isinstance(node, ast.Constant) and node.value is None


#: "不要第二个按钮"的哨兵名。
#:
#: **`None` 不算。** 它在 `ThemedDialog.__init__` 里是"没传，用默认的
#: 否(N)"，所以 `no_label=None` 出来的**仍然是两个按钮**——
#: `_notify` 就这样带着一个多余的「否(N)」活了很久，直到用户截图指出。
_NO_BUTTON_NAMES = ("NO_BUTTON",)


def _has_no_label(call: ast.Call) -> bool:
    """这个调用点是不是明确"只有一个按钮"。

    只有两种写法算：``no_label=NO_BUTTON``（哨兵），
    或者 ``no_label`` 压根没出现在这个调用里但按钮数由别处保证——
    后者静态看不出来，所以**只认哨兵**。
    """
    for keyword in call.keywords:
        if keyword.arg != "no_label":
            continue
        value = keyword.value
        if isinstance(value, ast.Name) and value.id in _NO_BUTTON_NAMES:
            return True
    return False


def _enclosing_functions(tree: ast.AST) -> list[ast.AST]:
    return [node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _scope_of(tree: ast.AST, call: ast.Call) -> ast.AST:
    """包含这个调用的**最小的那个函数**；不在任何函数里就返回整个模块。

    **必须限定作用域。** 早先对整个模块做 `ast.walk`：只要文件里
    *任何地方*出现过 "把 `ShowModal()` 赋给 X，再比较 X"，所有调用点
    都会被认为是"读了返回值"——包括那些真没读的。假阴性比假阳性危险：
    检查器会说"通过"，而缺陷还在。
    """
    best = tree
    best_size = None
    for function in _enclosing_functions(tree):
        if function.lineno <= call.lineno <= (function.end_lineno or function.lineno):
            size = function.end_lineno - function.lineno
            if best_size is None or size < best_size:
                best, best_size = function, size
    return best


def _reads_answer(tree: ast.AST, call: ast.Call) -> bool:
    """`ShowModal()` 的结果有没有被**用来做判断**。

    只认两种写法：

    * ``if dialog.ShowModal() == wx.ID_YES:``   —— 直接比较
    * ``answer = dialog.ShowModal()`` 之后 ``answer`` 出现在某个比较里

    比"文本里出现过 ID_YES"严格——后者会把注释也算进去。
    """
    scope = _scope_of(tree, call)

    def is_show_modal(node) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "ShowModal")

    # ① `answer = dialog.ShowModal()` → 记住 answer 这个名字
    names: set[str] = set()
    for node in ast.walk(scope):
        if (isinstance(node, ast.Assign) and is_show_modal(node.value)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)

    # ② 任何比较里出现 ShowModal() 本身，或出现上面记下的名字。
    #
    # **要比的是"任何位置"的比较，不只是 `if` 的条件。**
    # 实测漏过这一种（它就写在 `if` 里）：
    #
    #     if dialog.ShowModal() == wx.ID_YES:
    #
    # 那时我只在 `Assign` 节点下找比较，于是 `on_delete_selected`
    # 与 `on_clear` 两个**明明读了返回值**的地方被报成"没读"——假阳性。
    for node in ast.walk(scope):
        if not isinstance(node, ast.Compare):
            continue
        for side in (node.left, *node.comparators):
            if is_show_modal(side):
                return True
            if isinstance(side, ast.Name) and side.id in names:
                return True
    return False


def run(root: str) -> list[str]:
    source_dir = os.path.join(root, "src", "file_tracker")
    problems: list[str] = []
    checked = 0
    for name in sorted(os.listdir(source_dir)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(source_dir, name)
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "ThemedDialog"):
                continue
            checked += 1
            single = _has_no_label(node)
            reads = _reads_answer(tree, node)
            position = f"{name}:{node.lineno}"
            if single and reads:
                problems.append(
                    f"{position} 只给了一个按钮，却去比较 ShowModal() 的返回值"
                    f"——那个分支永远不会走到")
            elif not single and not reads:
                problems.append(
                    f"{position} 给了两个按钮，但没有读 ShowModal() 的返回值"
                    f"——两个按钮的行为必然完全一样（用户报过这个缺陷）")
    if not checked:
        problems.append("一个 ThemedDialog 调用点都没找到——检查器没有可检查的对象")
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
        print("对话框调用点检查未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("对话框调用点检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
