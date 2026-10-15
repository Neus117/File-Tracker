"""证明 :mod:`tools.check_dialogs` **真的会拦**它该拦的缺陷。

## 为什么需要这个

"返回通过"与"没有运行"在输出里长得一模一样。一个永远通过的检查器
比没有检查器更糟——它给的是虚假的安心。

所以这里造**必然该被拦**的样本，确认检查器报错；再造**必然该通过**的
样本，确认它不是"一律报错"。

样本直接取自用户报的那个真实缺陷：

> 失效删除确认弹窗有两个按钮，功能完全一致——关闭窗口。

用法::

    python tools/check_dialogs_negative.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_dialogs  # noqa: E402

#: 每个样本 = ``(名字, 源码, 期望是否被拦)``
SAMPLES: tuple[tuple[str, str, bool], ...] = (
    (
        "两按钮 + 不读返回值  ← **用户报的那个缺陷**",
        """
        def bad(self):
            dialog = ThemedDialog(self, self.theme, "已删除")
            dialog.ShowModal()
            dialog.Destroy()
        """,
        True,
    ),
    (
        "两按钮 + 只读默认标签也不读返回值",
        """
        def bad(self):
            d = ThemedDialog(self, theme, "x", yes_label=L("好", "OK"))
            d.ShowModal()
        """,
        True,
    ),
    (
        "单按钮（NO_BUTTON）+ 却去比较返回值（分支永远走不到）",
        """
        def bad(self):
            d = ThemedDialog(self, theme, "x", no_label=NO_BUTTON)
            if d.ShowModal() == wx.ID_YES:
                pass
        """,
        True,
    ),
    (
        "两按钮 + 就地比较（正确写法之一）",
        """
        def good(self):
            dialog = ThemedDialog(self, theme, "确定吗", title="确认")
            if dialog.ShowModal() == wx.ID_YES:
                self.do_it()
            dialog.Destroy()
        """,
        False,
    ),
    (
        "两按钮 + 先赋值再比较（正确写法之二）",
        """
        def good(self):
            dialog = ThemedDialog(self, theme, "确定吗", title="确认")
            answer = dialog.ShowModal()
            dialog.Destroy()
            if answer == wx.ID_YES:
                self.do_it()
        """,
        False,
    ),
    (
        "单按钮 + 不读返回值（正确写法：纯告知）",
        """
        def good(self):
            dialog = ThemedDialog(self, theme, "已删除",
                                  yes_label=L("好", "OK"), no_label=NO_BUTTON)
            dialog.ShowModal()
            dialog.Destroy()
        """,
        False,
    ),
    (
        "**同一个文件里**另一处读了返回值，本处没读 → 仍须被拦",
        """
        def reads_elsewhere(self):
            d = ThemedDialog(self, theme, "a", title="t")
            if d.ShowModal() == wx.ID_YES:
                pass
            d.Destroy()

        def bad(self):
            dialog = ThemedDialog(self, theme, "已删除")
            dialog.ShowModal()
            dialog.Destroy()
        """,
        True,
    ),
    (
        "**`no_label=None` 的陷阱**：它仍是两按钮，不读返回值就该被拦",
        """
        def bad(self):
            d = ThemedDialog(self, theme, "x", no_label=None)
            d.ShowModal()
        """,
        True,
    ),
    (
        "`no_label` 传的是真标签（仍算两按钮）→ 不读返回值就该被拦",
        """
        def bad(self):
            d = ThemedDialog(self, theme, "x", no_label=L("否", "No"))
            d.ShowModal()
        """,
        True,
    ),
)


def run_sample(source: str) -> list[str]:
    """把样本放进一个临时仓库结构里跑检查器。"""
    with tempfile.TemporaryDirectory(prefix="dialogcheck-") as scratch:
        package = os.path.join(scratch, "src", "file_tracker")
        os.makedirs(package)
        with open(os.path.join(package, "sample.py"), "w",
                  encoding="utf-8") as handle:
            handle.write(textwrap.dedent(source))
        return check_dialogs.run(scratch)


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
        print(f"      → {verb}"
              + (f"：{problems[0].split('——')[0].strip()}" if problems else ""))
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
