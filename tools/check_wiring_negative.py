"""接线检查的**阳性对照**：造必然被拦的样本，确认检查器真的会拦。

**阴性的检查结果必须先证明检测器真的跑了。**

这条纪律来自一次真实的代价：我曾开了一个代码检查门禁，它返回"干净"，
而它其实根本没运行——因为项目加载失败，脚本提前退出了。
**"返回通过"和"没有运行"在输出里长得一模一样。**

所以每一类检查都要有一个必然被拦的样本：

① 无人调用的方法
② 无人读取的常量
③ 代码里硬编码的开发机路径（而不是文档里解释这条路径曾经是缺陷）

## 样本本身也必须被验证

第一版把带缩进的 ``def`` 直接追加到文件末尾——那不是合法的 Python。
检查器报的是"语法错误"，于是阳性对照的输出是"拦住了但报错内容不符"，
**看起来像检查器坏了，其实是我造的样本坏了**。

现在注入之后会先 ``ast.parse`` 一次，样本不合法就直接断言失败：
样本坏了的时候，检查器的结论不作数。

做法：在临时目录里复制一份 ``src/`` 与 ``tests/``，往里注入缺陷，
对**那一份**跑检查，断言它返回非零且报错里提到预期的关键词。原仓库不受影响。

用法::

    python tools/check_wiring_negative.py
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKER = os.path.join(HERE, "check_wiring.py")


def _insert_after_imports(text: str, block: str) -> str:
    """在模块的 import 段之后插入一段代码。"""
    tree = ast.parse(text)
    last_import = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import = max(last_import, node.end_lineno)
    lines = text.splitlines(keepends=True)
    return "".join(lines[:last_import]) + block + "".join(lines[last_import:])


def inject_orphan_method(text: str) -> str:
    """把一个无人调用的方法插进模块里**第一个类**的末尾。

    **不能简单 append**：带缩进的 ``def`` 追加到文件末尾就是语法错误。
    """
    tree = ast.parse(text)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    if not classes:
        raise AssertionError("注入目标里没有类，无法把方法放进类体")

    target = classes[0]
    lines = text.splitlines(keepends=True)
    insert_at = target.body[-1].end_lineno
    indent = "    "
    block = (
        f"{indent}def orphan_method_nobody_calls(self):\n"
        f'{indent}    """注入的缺陷：全仓库没有任何调用点。"""\n'
        f"{indent}    return 1\n"
    )
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def inject_orphan_constant(text: str) -> str:
    """插入一个无人读取的大写常量。"""
    return _insert_after_imports(
        text, '\nORPHAN_CONSTANT_NOBODY_READS = "injected defect"\n',
    )


def inject_hardcoded_path(text: str) -> str:
    """插入一个硬编码开发机路径的常量。"""
    return _insert_after_imports(
        text,
        '\nDEVELOPER_MACHINE_PATH = "D:\\\\Work\\\\programming\\\\File Tracker"\n',
    )


def build_fixture(scratch: str, *, inject_into: str, injector) -> str:
    """把 src/ 与 tests/ 复制到临时目录并注入一段缺陷，返回该临时仓库根。

    **tests/ 必须复制真的那一份**（而不只是放一个占位文件）。
    "测试里的调用点算调用点"是这个检查器的一条判据，而 ``PathStore.replace_all``
    与 ``PathStore.count`` 正是只有测试在调用的公开接口。复制一份空的 tests/
    会让它们变成假阳性，把真正的注入缺陷淹掉。
    """
    fixture = os.path.join(scratch, "repo")
    os.makedirs(fixture, exist_ok=True)
    shutil.copytree(os.path.join(ROOT, "src"), os.path.join(fixture, "src"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(fixture, "tools"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    tests_src = os.path.join(ROOT, "tests")
    if os.path.isdir(tests_src):
        shutil.copytree(tests_src, os.path.join(fixture, "tests"),
                        ignore=shutil.ignore_patterns("__pycache__"))
    else:
        os.makedirs(os.path.join(fixture, "tests"), exist_ok=True)

    target = os.path.join(fixture, "src", "file_tracker", inject_into)
    with open(target, "r", encoding="utf-8") as handle:
        text = handle.read()

    text = injector(text)

    # **注入后必须确认它仍然是合法的 Python。**
    # 样本自己坏了的话，"检查器没拦住"是个假结论——这正是第一版发生的事。
    try:
        ast.parse(text)
    except SyntaxError as error:
        raise AssertionError(
            f"阳性对照的样本注入后不是合法 Python（{error}）——"
            "先修样本，检查器的结论不作数"
        ) from error

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text)
    return fixture


def run_checker(fixture: str) -> tuple[int, str]:
    env = dict(os.environ)
    # 子进程也必须按 UTF-8 输出；否则中文报错在管道里变乱码，
    # 下面的关键词匹配会失败，把"拦住了"误判成"报错内容不符"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [sys.executable, "-X", "utf8",
         os.path.join(fixture, "tools", "check_wiring.py"), "--root", fixture],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, env=env,
    )
    return (result.returncode, (result.stdout or "") + (result.stderr or ""))


CASES = (
    ("无人调用的方法", "app.py", inject_orphan_method, "无人调用的方法"),
    ("无人读取的常量", "core.py", inject_orphan_constant, "无人读取的常量"),
    ("代码里硬编码开发机路径", "core.py", inject_hardcoded_path, "硬编码开发机路径"),
)


def main() -> int:
    print("接线检查器的阳性对照")
    print("（在临时目录里注入缺陷，不影响本仓库）")
    print()

    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="filetracker-wiring-neg-") as scratch:
        for name, target, injector, expected in CASES:
            try:
                case_dir = tempfile.mkdtemp(dir=scratch)
                fixture = build_fixture(case_dir, inject_into=target, injector=injector)
            except AssertionError as error:
                print(f"  [FAIL] {name} —— 样本本身有问题: {error}")
                failures.append(f"{name}: 样本无效")
                continue

            code, output = run_checker(fixture)

            if code == 0:
                print(f"  [FAIL] {name} —— 注入缺陷后检查器仍返回 0（它没在检查这件事）")
                failures.append(f"{name}: 检查器没有拦住")
                continue
            if expected not in output:
                print(f"  [FAIL] {name} —— 拦住了，但报错里没有 {expected!r}")
                print(f"         实际输出: {output.strip()[:400]}")
                failures.append(f"{name}: 报错内容不符")
                continue
            print(f"  [PASS] {name} —— 检查器拦住了，且报错指向正确的东西")

    print()
    if failures:
        print(f"阳性对照失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("三类缺陷检查都已被证明会拦。接线检查器本身是可信的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
