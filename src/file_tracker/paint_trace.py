"""行底色诊断：`FT_DEBUG_PAINT=1` 时，记录**每一次**行底色/选中状态的改动。

## 为什么需要它（这一段是这一轮最重要的结论）

用户报了"从导航窗格打开之后，记录列表那条是浅灰而不是蓝色"，
而我在**探针里怎么复现都是蓝的** —— 一共写了七个探针，全绿。

原因不是用户看错了，而是**探针复刻的是我以为的场景，不是他的场景**。
真正能定位的做法只有一条：**把仪器插进他的环境**，让程序自己在
真实数据、真实主题、真实 DPI 下说出"谁在什么时候把哪一行改成了什么色"。

所以这个模块存在的意义是**给用户跑一次**，不是给单元测试跑：

```powershell
$env:FT_DEBUG_FOCUS = "1"
$env:FT_DEBUG_PAINT = "1"
.\run.ps1
# 复现一次（从导航窗格「打开」/双击），然后关掉程序
# 报告写在 %APPDATA%\\File Tracker\\paint-trace.txt
```

## 设计上的三条克制

1. **默认完全关闭**：不看环境变量时 `install()` 直接返回，
   一行包装都不装 —— 正常使用时零开销、零风险。
2. **同一个 (行, 颜色) 只留最后一次**：悬停路径每秒会调很多次，
   全量记录会把报告冲成几千行、真正有用的信息被埋掉。
   "最后一次"正是判断"这行最终归谁管"所需要的那条。
3. **失败绝不影响功能**：整段包在 `try/except` 里。
   一个诊断工具把主程序搞崩，比它没装上糟糕得多。

## 为什么记"调用栈"

只记 `(行, 颜色)` 会得到"有 6000 次调用"这种没用的结论。
栈能直接回答**是谁**、**走了哪条路** ——
`_render_rows_now`（重建时的底色）、`_apply_selection_highlight`（两档高亮）、
还是别的地方。
"""

from __future__ import annotations

import os
import time
import traceback

import wx

#: 触发开关（环境变量）。
ENV_FLAG = "FT_DEBUG_PAINT"

#: **文件开关**：存在这个文件就等于打开诊断。
#
# ## 为什么光有环境变量不够（2026-10-17 实测）
#
# 用户按说明设了 `$env:FT_DEBUG_PAINT = "1"` 再跑 `run.ps1`，
# 而 `[PAINT]` **一行都没出来** —— 同时 `[focus]` 正常输出。
#
# 查证：在同一个 PowerShell 里 `python -c "import os;
# print(os.environ.get('FT_DEBUG_PAINT'))"` 打印的是 **`None`** ——
# 那个 `python` 根本不是 `run.ps1` 用的解释器，**环境变量没进到被测进程**。
#
# ⇒ **不能让"开诊断"依赖某条特定的启动路径。**
# 文件开关与启动方式无关：放个空文件就开，删掉就关，
# 而且用户能一眼看见"它现在是不是开着"。
ENABLE_FILE_NAME = "enable-paint-trace"

#: 焦点诊断的开关（上一轮加的，和行底色诊断配套）
ENV_FOCUS_FLAG = "FT_DEBUG_FOCUS"

#: 报告文件名（落在应用数据目录里，和配置、日志放一起）
REPORT_NAME = "paint-trace.txt"

#: 每条记录最多写几层调用栈
STACK_DEPTH = 6


def data_dir() -> str:
    """应用数据目录（配置、日志、报告都在这里）。"""
    try:
        from .core import app_data_path
        return app_data_path()
    except Exception:
        return os.path.expanduser("~")


def enable_file() -> str:
    """文件开关的完整路径（用户放/删这个文件来开关诊断）。"""
    return os.path.join(data_dir(), ENABLE_FILE_NAME)


def enabled() -> bool:
    """诊断是否打开：**环境变量或文件开关**，任一即可。"""
    return bool(os.environ.get(ENV_FLAG)) or os.path.exists(enable_file())


def how_enabled() -> str:
    """打开诊断的到底是哪一个开关（写进报告，便于核对）。"""
    if os.environ.get(ENV_FLAG):
        return f"环境变量 {ENV_FLAG}={os.environ[ENV_FLAG]!r}"
    if os.path.exists(enable_file()):
        return f"文件开关 {enable_file()}"
    return "（未打开）"


def focus_debug_enabled() -> bool:
    """焦点诊断是否打开。"""
    return bool(os.environ.get(ENV_FOCUS_FLAG))


# ----------------------------------------------------------------------
# 焦点诊断（`FT_DEBUG_FOCUS`）
#
# 和行底色诊断放在同一个模块里，理由是**它们是同一个问题的两只眼睛**：
#   * `FT_DEBUG_FOCUS` —— 键盘焦点给了谁、选中落在哪、**存着**什么色
#   * `FT_DEBUG_PAINT` —— 每一次有什么东西被改成了什么色、**是谁改的**
# "存着蓝、看着灰"这个现象正好落在两者之间，所以两个开关一起开最有信息量。
# ----------------------------------------------------------------------

def focus_before(frame, path: str, from_tree: bool) -> None:
    """`record_accessed_path` 开头打一行：这次是从哪儿发起的。"""
    if not focus_debug_enabled():
        return
    print(f"[focus] record_accessed_path({path!r})")
    print(f"[focus]   _focus_pane = {getattr(frame, '_focus_pane', None)!r}"
          f"  ⇒ from_tree = {from_tree}")
    print(f"[focus]   before focus = {window_focus_name()}")


def focus_after(frame) -> None:
    """把焦点交给记录列表**之后**打一行。

    这里同时报告"存着的底色" —— 注意它**永远**是设进去的那个值，
    与屏幕上画成什么无关。这一点是上一轮最大的教训：
    **属性读回能证明"设对了"，不能证明"画对了"**。
    """
    if not focus_debug_enabled():
        return
    control = frame.list_ctrl
    print(f"[focus]   after focus = {window_focus_name()}"
          f"  (expected ListCtrl)")
    selected = control.GetFirstSelected()
    stored = (html_colour(control.GetItemBackgroundColour(selected))
              if selected >= 0 else "?")
    print(f"[focus]   selected = {selected}  stored colour = {stored}")
    print("[focus]   ⚠️ 上面那个颜色是**控件里存着的**，不是屏幕上画出来的；"
          "要判断'画成什么'，请同时开 FT_DEBUG_PAINT=1")


def focus_set_focus_failed(error: BaseException) -> None:
    """`SetFocus()` 抛异常时打一行。"""
    if focus_debug_enabled():
        print(f"[focus]   SetFocus raised: {error!r}")


def window_focus_name() -> str:
    """当前键盘焦点所属的控件类名（取不到返回 `None`）。"""
    try:
        focus = wx.Window.FindFocus()
        return type(focus).__name__ if focus else "None"
    except Exception:
        return "?"


class PaintTracer:
    """把列表控件上"改外观"的调用全部记下来。"""

    #: 需要盯的方法。前三项决定"画成什么"，后两项决定"谁是选中/焦点"。
    WATCHED = ("SetItemBackgroundColour", "SetItemTextColour", "SetItemState",
               "Select", "SetFocus", "Refresh")

    #: 要看内部状态的那个方法（画两档高亮的入口）。
    HIGHLIGHT = "_apply_selection_highlight"

    def __init__(self, frame, report_path: str) -> None:
        self.frame = frame
        self.control = frame.list_ctrl
        self.report_path = report_path
        self.started = time.time()
        self.lines: list[str] = []
        #: 已经出过报告没有（`on_close` 与退出兜底各会调一次 `dump`）
        self.dumped = False
        #: 打开诊断的是哪个开关（环境变量还是文件），写进报告便于核对
        self.opened_by = how_enabled()
        #: `_apply_selection_highlight` 的两种结局各发生了几次
        #: （**这两个数是关键判据**：早退次数多 ⇒ 它跑了却没画）
        self.highlight_painted = 0
        self.highlight_early = 0
        #: 上一次记录的 (选中行, paint_key)，用来只在状态真的变了时写一行
        self.last_highlight_state: tuple | None = None
        #: (方法, 行号, 颜色) → 最后一次的整行文本，保证"最后一次"胜出
        self.last: dict[tuple, str] = {}
        self.order: list[tuple] = []
        self.counts: dict[tuple, int] = {}

    # -- 安装 ----------------------------------------------------------
    def install(self) -> None:
        """包装那几个方法。**任何一步失败都整体放弃**，不半装。

        装完会打一行 `[PAINT]` 自报状态 —— **这一行不能省**：
        这一轮就是因为"没打印任何东西"而查不出"到底装没装上"。
        诊断工具必须能自证"我在运行"。
        """
        try:
            wrapped = []
            for name in self.WATCHED:
                original = getattr(self.control, name, None)
                if original is None:
                    # 这个 wx 构建里没有该方法：跳过，而不是让初始化失败
                    self._note_raw(f"（该版本没有 {name}，未跟踪）")
                    continue
                setattr(self.control, name, self._wrap(name, original))
                wrapped.append(name)
            self._note_raw(f"= 开始记录：主题="
                           f"{'dark' if self.frame.theme.is_dark else 'light'}"
                           f"  行数={self.control.GetItemCount()}"
                           f"  选中={self.control.GetFirstSelected()}")
            self._watch_highlight()
            print(f"[PAINT] 行底色记录器已装上"
                  f"（开关 = {self.opened_by}；已包装 {len(wrapped)} 个方法："
                  f"{', '.join(wrapped)}）")
            print(f"[PAINT] 复现一次操作，然后**关掉窗口**；"
                  f"报告会写到 {self.report_path}")
        except Exception as error:       # pragma: no cover - 诊断自身不能拖垮程序
            self._note_raw(f"（安装失败，诊断关闭：{error!r}）")
            print(f"[PAINT] 安装失败，诊断关闭：{error!r}")

    def _wrap(self, name: str, original):
        tracer = self

        def wrapper(*args, **kwargs):
            # **先记后做**：即使原方法抛异常，我们也留下了"是谁调用的"
            try:
                tracer._note(name, args)
            except Exception:
                pass
            return original(*args, **kwargs)

        wrapper.__name__ = f"ft_traced_{name}"
        return wrapper

    def _watch_highlight(self) -> None:
        """把 `_apply_selection_highlight` 的**内部状态**也记下来。

        ## 为什么光盯控件方法不够（2026-10-17，用户真实报告）

        报告显示选中行 31 在 **+5083ms** 被设成选中，却直到 **+8372ms**
        （鼠标移出列表时）才被画成蓝色 —— **中间 3.3 秒是白的**，
        而这段时间里**没有任何一次底色调用**。

        ⇒ 只有两种可能，而报告分不出来：

        * 它**被 `_paint_key` 早退吃掉了**（跑了但一个像素都没画）
        * 它**抛异常被静默吞了**（`except Exception: pass`，见那里的注释）

        这两种的修法完全不同，所以必须把"进去 / 早退 / 抛异常"分开记：
        `_paint_key` 前后**没变** = 早退；变了 = 真画了。
        """
        frame = self.frame
        original = getattr(frame, self.HIGHLIGHT, None)
        if original is None:
            self._note_raw(f"（该版本没有 {self.HIGHLIGHT}，未跟踪）")
            return
        tracer = self

        def wrapper():
            before_key = getattr(frame, "_paint_key", "缺")
            before_sel = tracer.control.GetFirstSelected()
            try:
                result = original()
                error = ""
            except Exception as exc:          # 真被吞掉的那种，这里抓得到
                result, error = None, repr(exc)
            after_key = getattr(frame, "_paint_key", "缺")

            # ⚠️ **不能每次调用都写一行**：这个方法挂在鼠标移动路径上
            # （`on_list_motion` → `_set_hover_row` → 这里），
            # 记录数上千时鼠标划几下就是几千行，真正有用的信息会被冲掉。
            #
            # 但**状态真的变了就必须记** —— 尤其是这一种：
            #   **选中项已经变了，`_paint_key` 却没变**
            #   ⇒ 说明它这次**没画**，而那一行就没人上色。
            #   屏幕上的表现正是"选中了，却是白的"。这一条是本轮最关键的判据。
            if error:
                tracer._note_raw(
                    f"[PAINT] {tracer.stamp():>12}  "
                    f"{tracer.HIGHLIGHT}() **抛异常（原来被静默吞掉）**：{error}")
                return result
            if before_key == after_key:
                tracer.highlight_early += 1
            else:
                tracer.highlight_painted += 1

            state = (before_sel, after_key)
            if state != tracer.last_highlight_state:
                tracer.last_highlight_state = state
                if before_sel >= 0 and before_key == after_key:
                    tracer._note_raw(
                        f"[PAINT] {tracer.stamp():>12}  {tracer.HIGHLIGHT}()  "
                        f"**选中={before_sel} 但一个像素都没画**"
                        f"（键 {before_key} 没变，被早退吃掉）")
                else:
                    tracer._note_raw(
                        f"[PAINT] {tracer.stamp():>12}  {tracer.HIGHLIGHT}()  "
                        f"选中={before_sel}  键 {before_key} → {after_key}"
                        f"  {'画了' if before_key != after_key else '（无选中，跳过）'}")
            return result

        wrapper.__name__ = f"ft_traced{self.HIGHLIGHT}"
        setattr(frame, self.HIGHLIGHT, wrapper)

    # -- 记录 ----------------------------------------------------------
    def stamp(self) -> str:
        """当前时刻（相对记录开始），用于给不带时间戳的手写条目对齐时间线。"""
        return f"+{(time.time() - self.started) * 1000:.1f}ms"

    def _note_raw(self, text: str) -> None:
        self.lines.append(text)

    def _note(self, name: str, args: tuple) -> None:
        focus = window_focus_name()
        try:
            active = bool(self.control.GetTopLevelParent().IsActive())
            selected = self.control.GetFirstSelected()
            top = self.control.GetTopItem()
        except Exception:
            active, selected, top = False, -1, -1

        if name in ("SetItemBackgroundColour", "SetItemTextColour"):
            row, colour = args[0], args[1]
            what = "底色" if name == "SetItemBackgroundColour" else "文字"
            detail = f"{what}(row={row}, {html_colour(colour)})"
        elif name == "SetItemState":
            detail = f"状态(row={args[0]}, set={args[1]}, clear={args[2] if len(args) > 2 else 0})"
        elif name == "Select":
            detail = f"选中(row={args[0]}, {args[1]})"
        else:
            detail = f"{name}()"

        stamp = f"+{(time.time() - self.started) * 1000:9.1f}ms"
        text = (f"[PAINT] {stamp} {detail:46} "
                f"focus={focus:<12} active={active!s:<5} "
                f"sel={selected} top={top}")

        key = (name, args[0] if args else None,
               html_colour(args[1]) if len(args) > 1 and hasattr(args[1], "GetAsString") else "")
        if key not in self.last:
            self.order.append(key)
        self.last[key] = text + self._stack()
        self.counts[key] = self.counts.get(key, 0) + 1

    @staticmethod
    def _stack() -> str:
        """调用栈（从内到外），跳过 wx 自己的包装帧。"""
        try:
            frames = traceback.extract_stack()[:-2]
        except Exception:
            return ""
        picked: list[str] = []
        for frame in reversed(frames):
            name = os.path.basename(frame.filename)
            # **跳过 wx 的包装层**：`wx/_core.py`、`wx/_msw*.py` 之类
            # 夹在中间会把真正有用的那三帧挤出视野
            if name.startswith("_core") or name.startswith("_msw"):
                continue
            picked.append(f"{name}:{frame.lineno} {frame.name}")
            if len(picked) >= STACK_DEPTH:
                break
        return "\n         ← " + "\n         ← ".join(picked) if picked else ""

    # -- 收尾 ----------------------------------------------------------
    def _active(self) -> str:
        """窗口现在是不是激活的（读不到就如实说读不到）。"""
        try:
            return str(bool(self.control.GetTopLevelParent().IsActive()))
        except Exception:
            return "（读不到）"

    def report(self) -> str:
        """生成"最后一次操作是谁做的"清单。"""
        control = self.control
        try:
            selected = control.GetFirstSelected()
            stored = (html_colour(control.GetItemBackgroundColour(selected))
                      if selected >= 0 else "（没有选中）")
            top = control.GetTopItem()
            count = control.GetItemCount()
        except Exception as error:
            selected, stored, top, count = -1, f"（读不到：{error!r}）", -1, -1

        try:
            theme = self.frame.theme
            palette = (f"card={theme.card} row_hover={theme.row_hover} "
                       f"pinned_row={theme.pinned_row}")
        except Exception:
            palette = "（读不到主题）"

        blocks = [
            "",
            "=" * 78,
            "行底色报告（每个「行 + 颜色」只保留**最后一次**，所以下面是最终归属）",
            "=" * 78,
            f"诊断开关     = {self.opened_by}",
            f"记录时长     = {(time.time() - self.started):.1f} 秒",
            f"行数={count}  选中行={selected}  顶行={top}",
            f"选中行**存着**的底色 = {stored}",
            f"主题配色 = {palette}",
            f"**窗口此刻激活吗** = {self._active()}",
            "",
            "  ⚠️ 这一条很重要：**未激活窗口里的 ListView，Windows 会用自己那套",
            "     非活动选中色（实测 #F0F0F0）盖掉我们设的底色** ——",
            "     此时「存着蓝、看着灰」是**系统的行为**，不是本程序的配色问题。",
            "     判据：看下面有没有 `active=False` 的条目。",
            "",
            "── 怎么读这份报告（只看这一段就够）──",
            "  1. 找下面「选中行」那几行（row = 上面的选中行号）",
            "  2. 看**最后一次**是谁、把它写成了什么颜色",
            "     * 最后写成 row_hover ⇒ 屏幕上就是浅灰，调用栈里的函数就是元凶",
            "     * 最后写成系统高亮色，而屏幕仍是灰",
            "       ⇒ **问题在程序之外**（窗口未激活 / 被遮挡 / 另一处覆盖），",
            "         不要再改本程序的配色",
            "  3. 三个记忆账本要与「选中行」一致；不一致就是「账本过期」那一类缺陷",
            "",
            "── 记忆账本（一旦和画面不同步，就会留下永远不变色的行）──",
            f"  _paint_key       = {getattr(self.frame, '_paint_key', None)!r}",
            f"  _highlighted_row = {getattr(self.frame, '_highlighted_row', None)!r}",
            f"  _hover_row       = {getattr(self.frame, '_hover_row', None)!r}",
            f"  _hover_painted   = {getattr(self.frame, '_hover_painted', None)!r}",
            f"  _focus_pane      = {getattr(self.frame, '_focus_pane', None)!r}",
            "",
            "── 画高亮那一步的两种结局（**这一条最容易被忽略**）──",
            f"  真画了（键变了）      = {self.highlight_painted} 次",
            f"  被 _paint_key 早退吃掉 = {self.highlight_early} 次",
            "  说明：早退是设计好的性能优化（鼠标在同一行内移动时不重画），",
            "        但**如果「选中行已经变了」它还是早退，那一行就没人上色** ——",
            "        屏幕上的表现正是「选中了，却是白的/灰的」。",
            "        上面「选中=N 但一个像素都没画」那几行就是这种情形。",
            "",
            f"── 最后一次外观改动（共 {len(self.order)} 种）──",
        ]
        for key in self.order:
            times = self.counts[key]
            suffix = f"   ×{times}" if times > 1 else ""
            blocks.append(f"  {self.last[key]}{suffix}")

        blocks.append("")
        blocks.append("── 说明 ──")
        blocks.append("  * 蓝 = SYS_COLOUR_HIGHLIGHT（本项目为 #0078D7）")
        blocks.append("  * row_hover = 预选那一档；若选中行最后被人写成 row_hover，")
        blocks.append("    那屏幕上就是浅灰 —— 这条清单会直接指出是哪个函数写的。")
        blocks.append("")
        blocks.append("── 一句话结论 ──")
        blocks.append("  " + self.verdict(selected))
        return "\n".join(self.lines + blocks)

    def verdict(self, selected: int) -> str:
        """用一行话说清"选中行最终是谁写的、写成什么"。

        **报告必须自己给结论。** 让用户（和下一个会话）在几百行清单里
        自己找，就是把"读懂"的成本推给了读的人 —— 那正是这一轮想避免的事。
        """
        wants = [key for key in self.order if key[1] == selected]
        if not wants:
            return (f"选中行 {selected} 上**没有任何**外观改动记录 ⇒ "
                    f"它现在画的就是重建时的底色（多半是主题白）。")
        picked = self.last[wants[-1]]
        head = picked.splitlines()[0]
        # ⚠️ **必须跳过本模块自己的帧**：栈顶永远是 `paint_trace.py:xxx wrapper`，
        # 它只说"记录器看到了这次调用"，回答不了"**是谁**调的"。
        # 第一版没跳，于是"元凶"指向了我的包装器 —— 等于没给答案。
        stack = [line.strip().lstrip("← ").strip()
                 for line in picked.splitlines()[1:]]
        stack = [frame for frame in stack if "paint_trace.py" not in frame]
        first = stack[0] if stack else "（没有调用栈）"
        if "row_hover" in head or "#DCE9F7" in head.upper():
            return (f"选中行 {selected} **最后一次被写成预选灰** ⇒ 屏幕上是浅灰。"
                    f"元凶：{first}")
        if "#0078D7" in head.upper():
            return (f"选中行 {selected} **最后一次被写成系统高亮蓝**（{first}）。"
                    f"若屏幕上仍是灰 ⇒ **问题在程序之外**"
                    f"（窗口未激活 / 被遮挡 / 另一处覆盖），不要再改配色。")
        return f"选中行 {selected} 最后一次是：{head}（{first}）—— 既不是蓝也不是预选灰。"

    def dump(self) -> None:
        """把报告写到文件（并打一份到控制台）。**不抛异常**。

        可以安全地被调用多次（`on_close` 一次、进程退出兜底一次）。
        """
        try:
            text = self.report()
        except Exception as error:       # pragma: no cover
            text = f"（生成报告失败：{error!r}）"
        try:
            with open(self.report_path, "w", encoding="utf-8") as handle:
                handle.write(text)
            self.dumped = True
            print(f"[PAINT] 报告已写入 {self.report_path}")
        except OSError as error:
            print(f"[PAINT] 写报告失败：{error!r}")
        print(text)

    def register_exit_hook(self) -> None:
        """**进程退出兜底**：保证报告一定会落盘。

        ## 为什么需要兜底

        正常关窗走 `on_close`，那里会 `dump()`。但用户「退出」的方式不止一种：

        * 点窗口的 ×             → 走 `on_close` ✅
        * **直接关掉控制台窗口**  → 进程被结束，`on_close` **不会跑** ❌
        * Ctrl+C                 → 同上 ❌

        而这一轮已经踩过一次"报告没生成、于是什么都看不到"。
        诊断工具的价值全在"拿得到读数"上 —— **必须假定用户会用最省事的方式退出**。
        """
        import atexit

        def on_exit() -> None:
            if self.dumped:
                return
            print("[PAINT] 窗口没走到 on_close，改由进程退出时出报告")
            self.dump()

        self.dumped = False
        atexit.register(on_exit)


def html_colour(colour) -> str:
    """`wx.Colour` → `#RRGGBB`；拿不到就返回 `repr`。"""
    try:
        return colour.GetAsString(wx.C2S_HTML_SYNTAX).upper()
    except Exception:
        return repr(colour)


def report_path() -> str:
    """报告落在应用数据目录（和 config.json 放一起，用户好找）。"""
    return os.path.join(data_dir(), REPORT_NAME)


def report_failed(error: BaseException) -> None:
    """出报告失败时打一行（`app.on_close` 用）。"""
    print(f"[PAINT] 出报告失败：{error!r}")


def install(frame) -> "PaintTracer | None":
    """按**环境变量或文件开关**决定要不要装；返回 tracer 供出报告时用。

    **调用方只需要**：

    ```python
    tracer = install(self)          # 没开开关时返回 None
    self._paint_tracer = tracer
    ```
    然后在关窗时调 `tracer.dump()`（退出兜底已在 `install` 里注册好）。
    """
    if not enabled():
        # **没开时不打印任何东西** —— 正常使用时控制台必须是干净的
        return None
    try:
        tracer = PaintTracer(frame, report_path())
        tracer.install()
        tracer.register_exit_hook()
        return tracer
    except Exception as error:           # pragma: no cover
        print(f"[PAINT] 诊断没能装上（不影响使用）：{error!r}")
        return None
