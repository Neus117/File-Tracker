"""接线检查：找出"定义了却从来没有人读取"的东西，以及硬编码的开发机路径。

这一类缺陷的特征是：**代码读起来完全正确、运行不报错、只是不生效。**
Roboc 项目里同样的检查第一次运行就找出了 ``--export-reg``。

## 为什么是 Python 而不是 PowerShell

第一版用 PowerShell 写，**在中文源码上不可用**：Windows PowerShell 5.1
读没有 BOM 的 UTF-8 文件时按 ANSI（本机是 GBK）解码。Python 源码是不带 BOM 的
UTF-8，于是所有中文变成乱码，连行列号都对不上。

顺带发现更根本的问题：**正则数名字出现次数这种做法，在 AST 面前没有理由存在。**
Python 自带 ``ast``，能精确区分"定义""调用""注释里提了一句""字符串里写了一个名字"。
现在改成走 AST，不再剥注释、不再数出现次数。

## 查四项

① **方法定义了但无人调用** —— 对应本项目最贵的历史缺陷：``set_icon`` 与
   ``load_last_directory`` 各被定义了两次，Python 静默用后一个，前一个成了死代码，
   而两份的失败处理还不一样。

② **模块级常量定义了但无人读取** —— 原 ``accessed_paths.json`` 就是这一类。

③ **硬编码的开发机绝对路径** —— 原实现里那三处 ``D:\\Work\\...``。

④ **声明了却不被使用的配置键**。

## 这个门禁必须自己验证它真的会拦

见 :mod:`tools.check_wiring_negative`：它造必然被拦的样本，确认本脚本报错。
**阴性的结果必须先证明检测器跑了**——"返回通过"和"没有运行"在输出里长得一样。

用法::

    python tools/check_wiring.py
    python tools/check_wiring.py --root <仓库根目录>
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

#: 由 wx 框架或程序入口调用，静态分析看不到常规调用点
FRAMEWORK_METHODS = {
    "OnInit", "OnPaint", "OnLeftDown", "OnLeftUp", "OnRightDown", "OnRightUp",
    "OnGetItemAttr", "SetBitmap", "SetLabel", "SetBackgroundColour",
    # wx 的尺寸协商：sizer 通过 C++ 虚函数调用，Python 侧没有调用点
    "DoGetBestSize", "DoGetBestClientSize",
    "main",
}

#: 故意保留而不读取的常量：它们的价值是"记录结论"，不是"参与运行"
INTENTIONALLY_UNREAD = {
    # win32.py 里的 LV* 常量是"按列居中为什么没走原生消息"这段结论的存档。
    # 删掉它们，下一个人还会把那条路再走一遍。
    "LVM_GETCOLUMNWIDTH": "win32: LVM_SETCOLUMN 失败尝试的记录",
    "LVM_SETCOLUMN": "win32: 同上",
    "LVM_GETCOLUMN": "win32: 同上",
    "LVM_SETITEMSPACING": "win32: 同上",
    "LVM_SETEXTENDEDLISTVIEWSTYLE": "win32: 同上",
    "LVCF_FMT": "win32: 同上",
    "LVCF_WIDTH": "win32: 同上",
    "LVCF_TEXT": "win32: 同上",
    "LVCF_SUBITEM": "win32: 同上",
    "LVCFMT_LEFT": "win32: 同上",
    "LVCFMT_RIGHT": "win32: 同上",
    "LVCFMT_CENTER": "win32: 同上",
    "LVS_EX_DOUBLEBUFFER": "win32: 原生控件扩展样式备查",
    "LVS_EX_FULLROWSELECT": "win32: 同上",
    "LVS_EX_GRIDLINES": "win32: 同上",
}

#: 开发机上的绝对路径特征。放在**代码**里（而不是注释）就算缺陷。
HARDCODED_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]+Work[\\/]+programming"),
    re.compile(r"C:[\\/]+Users[\\/]+Neus117"),
)


class SourceFile:
    """一个已解析的源文件。"""

    def __init__(self, path: str, root: str):
        self.path = path
        self.name = os.path.relpath(path, root).replace("\\", "/")
        with open(path, "r", encoding="utf-8") as handle:
            self.text = handle.read()
        self.lines = self.text.splitlines()
        try:
            self.tree = ast.parse(self.text, filename=path)
        except SyntaxError as error:
            raise ValueError(f"{self.name}: 语法错误 {error}") from error


def collect_references(tree: ast.AST) -> set[str]:
    """收集整个模块里所有"被**读取**的名字"。

    **必须区分读取与定义。** 第一版把所有 ``ast.Name`` 都算成引用，
    于是一个模块级常量**只要被定义出来就算"被引用了"**——
    阳性对照立刻抓到了这个漏洞：注入的孤儿常量没有被拦住。

    现在只认三种形态：

    * ``ast.Name`` **且 ctx 是 Load** —— 真正的读取。
      赋值目标的 ``Name`` 是 Store，不是引用；``x += 1`` 里的 ``x`` 同时有
      Load 与 Store，那个 Load 会（正确地）被算进来。
    * ``ast.Attribute`` —— ``self.foo`` / ``Config.save``。
      函数被取出来当回调传（``on_click=self.on_open``）走的是这条路。
    * ``ast.Call`` —— ``record_access(...)`` 这类直接调用。

    ``ast`` 天然不含注释，而字符串是 ``ast.Constant``——所以"只在文档里
    被提到"的死方法不会被误判为活的。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
    return names


def find_method_definitions(source: SourceFile) -> list[tuple[str, int]]:
    """模块里所有**方法**定义（缩进在类里的 ``def``）与其行号。"""
    found: list[tuple[str, int]] = []
    for node in ast.walk(source.tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((item.name, item.lineno))
    return found


def find_module_constants(source: SourceFile) -> list[tuple[str, int]]:
    """模块级大写常量与其行号。"""
    found: list[tuple[str, int]] = []
    for node in source.tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]

        for target in targets:
            if isinstance(target, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", target.id):
                found.append((target.id, node.lineno))
    return found


def check_hardcoded_paths(source: SourceFile) -> list[str]:
    """代码里的硬编码开发机路径。

    **必须排除文档字符串。** 第一次跑的时候它把 ``core.resource_path`` 的
    docstring 报成了缺陷——而那段 docstring 恰恰是在**说明**这条路径曾经是个
    缺陷（"兜底又是开发机上的 ``D:\\Work\\...``，也不存在"）。把解释历史的文档
    当成缺陷，等于让人把解释删掉。

    判据：只要这个字符串常量是某个函数/类/模块的 docstring 就跳过。
    """
    docstrings: set[int] = set()
    for node in ast.walk(source.tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstrings.add(id(first.value))

    problems: list[str] = []
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        for pattern in HARDCODED_PATTERNS:
            if pattern.search(node.value):
                problems.append(
                    f"{source.name}:{node.lineno}  代码里的硬编码开发机路径: {node.value!r}"
                )
                break
    return problems


def check_config_keys(sources: dict[str, SourceFile]) -> list[str]:
    """``config.py`` 里写进 ``_data`` 的键，是否都有对应的读取点。"""
    config = sources.get("config.py")
    if config is None:
        return ["找不到 config.py，配置键检查没有执行"]

    keys: set[str] = set()
    for node in ast.walk(config.tree):
        # self._data["key"] = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)):
                    keys.add(target.slice.value)
        # self._data.get("key")
        #
        # **必须是 `self._data.get(...)`，不能是任意 `.get(...)`。**
        # 踩过：早先只判 `func.attr == "get"`，于是
        # `os.environ.get("APPDATA")` 也被当成了一个配置键，
        # 报"配置键没有读取点: APPDATA"——一个环境变量被当成了配置项。
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "_data"):
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        keys.add(argument.value)

    problems: list[str] = []
    for key in sorted(keys):
        # 该键至少要被读取一次（出现在 config.py 的字符串常量里 ≥ 2 次：写 + 读）
        occurrences = sum(
            1
            for node in ast.walk(config.tree)
            if isinstance(node, ast.Constant) and node.value == key
        )
        if occurrences < 2:
            problems.append(f"配置键没有读取点: {key}")
    return problems


def run(root: str) -> tuple[list[str], dict[str, int]]:
    """跑完四项检查。

    :return: ``(问题列表, 统计信息)``
    """
    source_dir = os.path.join(root, "src", "file_tracker")
    if not os.path.isdir(source_dir):
        return ([f"找不到源码目录: {source_dir}"], {})

    paths = sorted(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.endswith(".py")
    )
    if not paths:
        return ([f"{source_dir} 下没有 .py 文件——检查器没有可检查的对象"], {})

    sources = {}
    problems: list[str] = []
    for path in paths:
        try:
            source = SourceFile(path, root)
        except ValueError as error:
            problems.append(str(error))
            continue
        sources[os.path.basename(path)] = source

    # 全仓库的引用集合：一个方法可能在别的模块里被调用，
    # **测试也是调用点**。第一版只看 src/，于是 `PathStore.replace_all` 与
    # `PathStore.count` 被报成死代码——而它们正是测试在验证的公开接口。
    # "只有测试用得到"和"谁都不用"是两件事，前者是接口，后者是垃圾。
    all_references: set[str] = set()
    for source in sources.values():
        all_references |= collect_references(source.tree)

    tests_dir = os.path.join(root, "tests")
    tests_scanned = 0
    if os.path.isdir(tests_dir):
        for name in sorted(os.listdir(tests_dir)):
            if not name.endswith(".py"):
                continue
            try:
                with open(os.path.join(tests_dir, name), "r", encoding="utf-8") as handle:
                    test_tree = ast.parse(handle.read())
            except (OSError, SyntaxError):
                continue
            all_references |= collect_references(test_tree)
            tests_scanned += 1

    # ① 方法调用点
    method_count = 0
    for source in sources.values():
        for name, line in find_method_definitions(source):
            method_count += 1
            if name.startswith("_") or name in FRAMEWORK_METHODS:
                continue
            if name not in all_references:
                problems.append(f"无人调用的方法: {source.name}:{line}  {name}")

    # ② 常量读取点
    constant_count = 0
    skipped = 0
    for source in sources.values():
        for name, line in find_module_constants(source):
            constant_count += 1
            if name in INTENTIONALLY_UNREAD:
                skipped += 1
                continue
            if name not in all_references:
                problems.append(f"无人读取的常量: {source.name}:{line}  {name}")

    # ③ 硬编码路径
    for source in sources.values():
        problems.extend(check_hardcoded_paths(source))

    # ④ 配置键
    problems.extend(check_config_keys(sources))

    stats = {
        "files": len(sources),
        "tests": tests_scanned,
        "methods": method_count,
        "constants": constant_count,
        "constants_skipped": skipped,
    }
    return (problems, stats)


def _force_utf8_output() -> None:
    """把 stdout/stderr 切到 UTF-8。

    **必须做这一步。** 本机 Windows 控制台的默认编码是 GBK，而这个脚本的输出
    全是中文；被父进程以管道捕获时，GBK 编码的字节会被对方按 UTF-8 解码，
    变成一串乱码——**阳性对照脚本因此无法在输出里匹配它期待的关键词**，
    于是"检查器其实拦住了"被误判成"报错内容不符"。踩过一次。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main() -> int:
    _force_utf8_output()

    parser = argparse.ArgumentParser(description="File Tracker 接线检查")
    parser.add_argument("--root", default=None, help="仓库根目录")
    args = parser.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.abspath(root)

    problems, stats = run(root)

    if stats:
        print(f"已解析 {stats['files']} 个源文件（走 AST，注释与字符串天然被排除）")
        print(f"引用点另外扫描了 {stats['tests']} 个测试文件——测试也是调用点")
        print()
        print(f"① 方法调用点检查      —— 共 {stats['methods']} 个方法")
        print(f"② 模块级常量读取点检查 —— 共 {stats['constants']} 个常量"
              f"（另有 {stats['constants_skipped']} 个已注明的例外）")
        print("③ 硬编码开发机路径检查")
        print("④ 配置键读取点检查")
        print()

    if problems:
        print(f"接线检查失败，{len(problems)} 处：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("接线检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
