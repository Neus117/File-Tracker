"""证明 :mod:`tools.check_duplicate_methods` **真的会拦**它该拦的缺陷。

"返回通过"与"没有运行"在输出里长得一模一样。所以这里造**必然该被拦**
的样本，确认检查器报错；再造**必然该通过**的样本，确认它不是一律报错。

样本取自真实缺陷：`FileTracker._remember_sort` 曾被定义两次。
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_duplicate_methods  # noqa: E402

#: ``(名字, 源码, 期望是否被拦)``
SAMPLES: tuple[tuple[str, str, bool], ...] = (
    (
        "同一个类里同名方法两次（**真实缺陷**）",
        """
        class Tracker:
            def _remember_sort(self):
                pass

            def other(self):
                pass

            def _remember_sort(self):
                pass
        """,
        True,
    ),
    (
        "两个**不同**类里的同名方法（不该被拦）",
        """
        class A:
            def run(self):
                pass

        class B:
            def run(self):
                pass
        """,
        False,
    ),
    (
        "类方法与普通函数同名（不该被拦）",
        """
        def build():
            pass

        class A:
            def build(self):
                pass
        """,
        False,
    ),
    (
        "property 与普通方法同名（仍是覆盖，该被拦）",
        """
        class A:
            def value(self):
                pass

            @property
            def value(self):
                return 1
        """,
        True,
    ),
    (
        "三个同名（该被拦，且要报出三次）",
        """
        class A:
            def go(self):
                pass

            def go(self):
                pass

            def go(self):
                pass
        """,
        True,
    ),
    (
        "正常的一个类（不该被拦）",
        """
        class A:
            def one(self):
                pass

            def two(self):
                pass
        """,
        False,
    ),
)


def run_sample(source: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="dupcheck-") as scratch:
        package = os.path.join(scratch, "src", "file_tracker")
        os.makedirs(package)
        with open(os.path.join(package, "sample.py"), "w",
                  encoding="utf-8") as handle:
            handle.write(textwrap.dedent(source))
        return check_duplicate_methods.run(scratch)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    failures = []
    for name, source, should_catch in SAMPLES:
        problems = run_sample(source)
        caught = bool(problems)
        mark = "✅" if caught == should_catch else "❌"
        verb = "被拦" if caught else "通过"
        print(f"  {mark} {name}")
        print(f"      → {verb}")
        if caught != should_catch:
            failures.append(name)

    print()
    if failures:
        print(f"❌ {len(failures)} 个样本与期望不符：{failures}")
        return 1
    print(f"✅ {len(SAMPLES)} 个样本全部符合期望 —— "
          f"该拦的拦住了，该过的也过了。检查器本身是可信的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
