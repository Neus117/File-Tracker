"""探针的**自我保护**：不让 wx 弹模态框把探针（和用户）卡住。

## 为什么需要这个

用户反馈："我帮你点掉了这些窗口……我生怕你思考卡住又多等几十分钟。"

实际发生的事，一共三类，都是 **wx 的模态对话框**：

① **wx 断言框**（`wxWidgets Debug Alert`）。断言失败时 wx 弹一个框等用户
   点确认，而不是抛异常。没有人在旁边点，**进程就永远停在那里**。
   实测：`wx.StandardPaths.Get()` 在没有 `wx.App` 时就是这一种。

② **PyInstaller 的运行时错误框**（`Unhandled exception in script`）。
   打包后的程序崩溃时弹一个原生 `MessageBox`——探针是被动等它的。

③ **探针自己造的窗口没关**。

## 两道处理

* :func:`harden_wx` —— 在**建窗口之前**调：
  * `wx.DisableAsserts()`：断言不再弹框，改为抛/继续。
    这一条把"永远卡住"变成"立刻失败"，是本模块的核心。
  * 把一个默认的 `wx.App` 建出来（需要时），
    避免落到"没有 App 却调 App 级 API"这条路上。

* :func:`run_probe` —— 把探针脚本**当子进程跑并硬限时**。
  超时就杀，并把"超时"本身作为结论报出来。这样即使某个探针
  还是卡住了，卡住的也是子进程，不是整场会话。

## 用法

```python
from _probe_guard import harden_wx

harden_wx()                 # 必须在 import wx 之后、建窗口之前
import wx
app = wx.App()
```

整脚本级：

```python
from _probe_guard import run_probe
code, out = run_probe("probe_xxx.py", timeout=120)
```
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys


@contextlib.contextmanager
def client_dc(window):
    """`wx.ClientDC` 的上下文管理器 —— **必须在窗口销毁前释放**。

    ## 为什么需要它（2026-10-17 查到的偶发访问违例）

    探针里这么写很自然：

    ```python
    for x in range(...):
        dc = wx.ClientDC(ctrl)     # 每次迭代新建
        ...                        # 用完不管
    frame.Destroy()                # ← 最后一个 dc 还活着！
    ```

    Python 里 `dc` 是**普通局部变量**，循环结束后最后一个仍然存活，
    直到函数返回或脚本结束才析构。**如果那时窗口已经 `Destroy()`，
    析构 DC 会去释放一个指向已销毁窗口的 HDC ⇒ 访问违例**
    （退出码 `-1073741819` / `0xC0000005`）。

    用户看到的
    `"python has stopped working / Error launching CrashSender.exe"`
    就是它 —— `CrashSender.exe` 是 WER 的收尸程序，不是原因。

    ## 用法

    ```python
    from _probe_guard import client_dc

    with client_dc(frame.list_ctrl) as dc:
        colour = dc.GetPixel(x, y)
    # 出了 with，DC 已经释放，之后再 Destroy 也安全
    ```

    产品代码**不需要**这个：那边 `dc` 都是方法内的局部变量，
    方法一返回就释放了。
    """
    import wx

    dc = wx.ClientDC(window)
    try:
        yield dc
    finally:
        # 显式删掉，别让它活到窗口销毁之后
        del dc


def pixel_at(window, x: int, y: int) -> tuple[int, int, int] | None:
    """读一个像素的 RGB；读不到返回 ``None``。

    **内部就用 :func:`client_dc`**，所以调用方不用管 DC 生命周期 ——
    这是探针里读像素的推荐写法。
    """
    try:
        with client_dc(window) as dc:
            colour = dc.GetPixel(int(x), int(y))
        return (colour.Red(), colour.Green(), colour.Blue())
    except Exception:
        return None

#: 进程级：只装一次
_hardened = False
#: `wx.Frame.Destroy` 的补丁是否已装（同样只装一次）
_destroy_patched = False


def _patch_frame_destroy() -> None:
    """让 `wx.Frame.Destroy()` 先把 `_closing` 置真，再真正销毁。

    ## 为什么（2026-10-17 查到的偶发崩溃）

    用户看到测试时偶尔弹：

    > "python has stopped working / Error launching CrashSender.exe"

    `CrashSender.exe` **不是我们程序带的**（环境里搜不到），它是
    **Windows 错误报告（WER）** 在 Python 进程真的崩了之后尝试启动的
    崩溃收集器 —— 它启动失败才弹出那个框。**所以那个框是"崩了"的
    二次症状，不是原因。**

    真正的链路：

    1. `_paint_column_separators()` 用 `wx.CallAfter`（异步）画竖线
    2. 探针直接 `frame.Destroy()`，**从不调用 `on_close`** ⇒ `_closing`
       永远是 `False`
    3. `Destroy()` 是**异步**的：排队的 `CallAfter` 可能**在窗口销毁之后**才跑
    4. 那时 `wx.ClientDC(self.list_ctrl)` 拿到的是**已失效的 HWND**，
       GDI 调用触发**访问违例** —— 而访问违例是 **C 层崩溃，不是 Python
       异常**，`try/except Exception` 抓不住它

    ⇒ 探针侧统一在这里补一刀：**销毁前先置 `_closing`**，
    排队中的绘制回调会自己提前返回（见 `_call_after` 的守卫）。

    产品侧另有独立防御（`:meth:`FileTracker._paint_column_separators``
    开头的 `IsBeingDeleted` 检查），两者互不依赖。
    """
    global _destroy_patched
    if _destroy_patched:
        return
    import wx

    original = wx.Frame.Destroy

    def guarded_destroy(self, *args, **kwargs):
        # 先关掉"窗口关闭后还会跑的回调"，再销毁
        try:
            self._closing = True
        except Exception:
            pass
        return original(self, *args, **kwargs)

    wx.Frame.Destroy = guarded_destroy
    _destroy_patched = True


def harden_wx(need_app: bool = False):
    """关掉 wx 的断言弹框（并可顺手把 `wx.App` 建出来）。

    :param need_app: 是否连 `wx.App` 一起建。**默认不建**——
        因为"有没有 App"本身就是被测的东西之一
        （见 `probe_standardpaths_hang.py`）；
        只有那些纯粹想跑界面、不希望被 App 缺失绊住的探针才传 ``True``。

    :return: 建出来的 `wx.App`（没建则返回 ``None``）。

    ## ⚠️ 调用方**必须接住**返回值

    踩过：写成 ``harden_wx(need_app=True)`` 而不赋值，于是那个 `wx.App`
    **立刻被垃圾回收**（引用计数归零），后面第一次用 `wx.Image` 就报

        wx._core.PyNoAppError: The wx.App object must be created first!

    ——**错误信息说"没有 App"，而代码明明建了**，很容易往错的方向查。

    正确写法::

        _APP = harden_wx(need_app=True)     # 接住它，活到脚本结束
    """
    global _hardened
    import wx

    if not _hardened:
        # **这一行是关键。** 断言框会阻塞到有人点它为止；
        # 关掉之后断言变成可恢复的失败，探针能继续或立刻报错。
        wx.DisableAsserts()
        _hardened = True

    # 探针都要建/销毁窗口 ⇒ 顺手装好"销毁前关回调"的补丁。
    # 它解决的是"偶发访问违例"，见 `_patch_frame_destroy` 的说明。
    _patch_frame_destroy()

    if not need_app:
        return None
    app = wx.App(redirect=False)
    if app is None:
        # 已经有 App 了：`wx.App()` 在重复构造时会失败，
        # 那种情况下返回现有的那个，让调用方仍有东西可接。
        app = wx.GetApp()
    return app


def install_excepthook() -> None:
    """把未捕获异常打清楚，**并保证非零退出码**。

    默认的 wx 程序崩溃时会弹原生框；探针要的是"一行能读的错误 + 非零退出"，
    这样 `run_probe` 才能判定失败，而不是靠人去点框。
    """
    def hook(kind, value, tb):
        import traceback

        traceback.print_exception(kind, value, tb, file=sys.stderr)
        # 交给默认钩子会再弹框（打包产物上），所以这里直接退
        os._exit(70)

    sys.excepthook = hook


def run_probe(script: str, timeout: int = 180,
              extra_args: tuple[str, ...] = ()) -> tuple[int, str]:
    """把探针当**子进程**跑，硬限时；超时就杀。

    :return: ``(退出码, 输出)``。超时返回 ``(-1, 输出 + 说明)``。

    **子进程里也装好护栏**：即使不知道探针内部做了什么，
    断言框也不会弹出来阻塞。做法是用 `-c` 先 import 护栏再跑脚本。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(os.path.dirname(os.path.dirname(here)), "src")
    bootstrap = (
        "import sys, runpy;"
        f"sys.path[:0]=[{here!r}, {src!r}];"
        "from _probe_guard import harden_wx, install_excepthook;"
        "install_excepthook(); harden_wx();"
        f"runpy.run_path({script!r}, run_name='__main__')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", bootstrap, *extra_args],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=os.path.dirname(here))
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as expired:
        # **超时是结论，不是意外。** 说明这个探针会在没人点框的情况下卡住。
        partial = ""
        for stream in (expired.stdout, expired.stderr):
            if stream:
                partial += (stream.decode("utf-8", "replace")
                            if isinstance(stream, bytes) else stream)
        return -1, (partial
                    + f"\n[护栏] {timeout}s 未退出，已强制结束。"
                      "多半是有人没点的模态框（wx 断言框 / 崩溃框）。\n")
