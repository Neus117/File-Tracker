"""Windows 原生消息封装：只用 ``ctypes``，不依赖 pywin32。

**这个模块只保留仍然在用的东西**，外加一段记录下来的失败尝试。

仍在用：

* :func:`system_uses_light_theme` / :func:`system_accent_color` —— 配色从系统读
* :func:`apply_rounded_corners` / :func:`set_title_bar_dark` —— Win11 窗口外观
* :func:`get_dpi_for_window` —— DPI 换算

**已经不用了，但保留常量与结构体**：``LVCOLUMN`` / ``LVM_*`` / ``LVCFMT_*``
以及 :class:`LVCOLUMN` 的实测布局。它们记录的是"按列居中"这件事为什么
最终没有走原生消息——见 :class:`file_tracker.app.FileTrackerListCtrl`。
删掉它们，下一个人还会把这条路再走一遍。
"""

from __future__ import annotations

import ctypes
import sys

# -- 消息号 ----------------------------------------------------------------

LVM_FIRST = 0x1000
LVM_GETCOLUMNWIDTH = LVM_FIRST + 29
LVM_SETCOLUMN = LVM_FIRST + 24
LVM_GETCOLUMN = LVM_FIRST + 25
LVM_SETITEMSPACING = LVM_FIRST + 51
LVM_SETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 54
LVM_GETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 55


#: 扩展样式位
#
#: ``WS_EX_CLIENTEDGE`` 是那个**由系统绘制的下凹 3D 边框**——
#: ``SetBackgroundColour`` 对它无效，深色主题下就是一圈白框。
#: 用户反馈的"导航窗格外框线仍是白色"就是它，见 :func:`remove_client_edge`。
WS_EX_CLIENTEDGE = 0x00000200

# -- 扩展样式（``LVS_EX_*``）------------------------------------------------
#
# 每一个都对应一次真实的用户反馈：
#   FULLROWSELECT 丢了 → "只有选中文字部分才能点击"
#   GRIDLINES 是**横竖都画**（用户只要列间竖线，所以改用自绘，见 header.py）
LVS_EX_GRIDLINES = 0x00000001
#: **热跟踪选择**——"光标在某一项上停留一段时间后，该项被**自动选中**"。
#:
#: .. warning::
#:    这**不是**资源管理器的"预选跟随"。我第一版就用错了它，
#:    用户实测"反应特别慢，有近一秒的延迟"——因为它是**带定时器**的，
#:    而且悬停久了会**真的选中**（把"预选"和"选中"混成了一档）。
#:    **不要再用它。** 正确的是 :data:`LVS_EX_TWOCLICKACTIVATE`。
LVS_EX_TRACKSELECT = 0x00000008
#: **热跟踪**（hot tracking）——"光标移到某项上时，它被**高亮但不被选中**"。
#:
#: 这正是用户说的"预选跟随"：选中一档、预选一档，两档颜色不同。
#: 官方文档（Extended List-View Styles）里 ``LVS_EX_ONECLICKACTIVATE``
#: 与 ``LVS_EX_TWOCLICKACTIVATE`` 都 "also enables hot tracking"，
#: 区别只在激活需要几次点击。
LVS_EX_TWOCLICKACTIVATE = 0x00000080
#: 单击即激活 —— 会把"单击只选中"变成"单击直接打开"，**刻意不开**。
LVS_EX_ONECLICKACTIVATE = 0x00000040
LVS_EX_FULLROWSELECT = 0x00000020
LVS_EX_DOUBLEBUFFER = 0x00010000

#: 不创建列头。**必须在 ``wx.ListCtrl`` 构造时拼进 style**——
#: 事后 ``SetWindowLong`` 设它无效（Windows 只在创建时看这个标志），
#: 详见 :func:`strip_column_header_style` 的说明。
LVS_NOCOLUMNHEADER = 0x4000

#: 不创建列头。**必须在 ``wx.ListCtrl`` 构造时拼进 style**——
#: 事后 ``SetWindowLong`` 设它无效（Windows 只在创建时看这个标志），
#: 详见 :func:`strip_column_header_style` 的说明。
WS_EX_CLIENTEDGE = 0x00000200


class LVCOLUMN(ctypes.Structure):
    """Win32 ``LVCOLUMN`` 结构体（``commctrl.h``）。

    **字段顺序是 ``mask, iSubItem, fmt, cx, ...``，``iSubItem`` 在第二位。**
    这一点踩过一次：按"直觉"把 ``iSubItem`` 放到末尾（紧挨 ``iImage``）时，
    结构体大小仍是 40 字节、``LVM_SETCOLUMN`` 仍返回成功，
    但 ``fmt`` 写进了错误的位置——**消息被正常处理，格式却从未改变**，
    而 ``LVM_GETCOLUMN`` 回读出来的是上一个字段的残留值。

    实测（`tools/probes/probe_native_lvm.py`）：用 ``mask = LVCF_SUBITEM`` 探测时，
    Windows 把值写在偏移 **40** 处，而 malloc 出来的缓冲区在偏移 8 之后
    完全没被改动——这直接否定了"iSubItem 在末尾"的假设。

    x64 布局（共 40 字节）::

        mask        0
        iSubItem    4
        fmt         8
        cx         12
        pszText    16   （8 字节对齐）
        cchTextMax 24
        iImage     28
        iOrder     32
    """

    _fields_ = [
        ("mask", ctypes.c_uint),
        ("iSubItem", ctypes.c_int),
        ("fmt", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("pszText", ctypes.c_wchar_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("iOrder", ctypes.c_int),
    ]


IS_WINDOWS = sys.platform == "win32"


def _send_message(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    """``SendMessageW``。非 Windows 平台返回 0。"""
    if not IS_WINDOWS:
        return 0
    return int(ctypes.windll.user32.SendMessageW(
        ctypes.c_void_p(hwnd), ctypes.c_uint(msg),
        ctypes.c_void_p(wparam), ctypes.c_void_p(lparam),
    ))


def invalidate_window(hwnd: int, erase: bool = True) -> bool:
    """让一个原生控件立刻重画。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(ctypes.windll.user32.InvalidateRect(
            ctypes.c_void_p(hwnd), None, bool(erase),
        ))
    except (OSError, AttributeError):
        return False



def set_item_spacing(hwnd: int, width: int, height: int) -> bool:
    """设置列表行间距（``LVM_SETITEMSPACING``）。

    ``lparam`` 是 ``MAKELPARAM(cx, cy)``：低 16 位宽、高 16 位高。
    任何一维为 -1 表示"该项保持不变"。负值必须按 16 位补码打包，
    否则 ``-1`` 会被当成 ``65535``。

    **注意**：这只对原生 ``SysListView32`` 有意义（``wx.ListCtrl`` 就是它）。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    packed = ((height & 0xFFFF) << 16) | (width & 0xFFFF)
    return bool(_send_message(hwnd, LVM_SETITEMSPACING, 0, packed))


def set_extended_style(hwnd: int, enable: int, mask: int | None = None) -> bool:
    """打开列表控件的扩展样式（``LVS_EX_*``），**保留其余位**。

    ## 一个踩过的 Win32 坑

    ``LVM_SETEXTENDEDLISTVIEWSTYLE`` 的语义是
    "**把 ``wparam`` 掩码覆盖的那些位，整体替换成 ``lparam``**"。
    所以 ``wparam`` 只给 ``LVS_EX_GRIDLINES``、``lparam`` 给 0 时，
    **并不只是关掉网格线**——它会把掩码之外的所有扩展样式一起清掉。
    我因此丢过 ``LVS_EX_FULLROWSELECT``，用户看到的现象是
    "只有选中文字部分才能点击"。

    正确做法：**先读当前值，改完再整体写回**（掩码给全部 32 位）。

    ## 判据是回读，不是返回值

    实测该消息成功时也**返回 0**（`tools/probes/probe_round6.py`），
    按返回值判断会把成功当失败。所以这里设置完回读确认。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    target = get_extended_style(hwnd)
    target |= enable if mask is None else (enable & mask)
    if mask is not None:
        target = (target & ~mask) | (enable & mask)
    # 掩码给全部 32 位，整体写回——这样不会误清其它位
    packed = (0xFFFFFFFF << 32) | (target & 0xFFFFFFFF)
    _send_message(hwnd, LVM_SETEXTENDEDLISTVIEWSTYLE, 0, packed)
    return (get_extended_style(hwnd) & target) == target


def clear_extended_style(hwnd: int, disable: int) -> bool:
    """**只清掉**指定的扩展样式位，保留其余。

    同样要先读再整体写回——理由见 :func:`set_extended_style`。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    target = get_extended_style(hwnd) & ~disable
    packed = (0xFFFFFFFF << 32) | (target & 0xFFFFFFFF)
    _send_message(hwnd, LVM_SETEXTENDEDLISTVIEWSTYLE, 0, packed)
    return (get_extended_style(hwnd) & disable) == 0


def get_extended_style(hwnd: int) -> int:
    """读列表控件当前的扩展样式位。"""
    if not IS_WINDOWS or not hwnd:
        return 0
    return _send_message(hwnd, LVM_GETEXTENDEDLISTVIEWSTYLE, 0, 0)


def hide_child_window(hwnd: int, class_name: str) -> bool:
    """把某个原生子控件**隐藏掉**（``ShowWindow(SW_HIDE)``）。

    **不要用这个来对付列表表头了**——见 :func:`strip_column_header_style`。
    留着是因为它对"已经建好的"子控件仍然有效（例如原生滚动条）。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    child = find_child_window(hwnd, class_name)
    if not child:
        return False
    SW_HIDE = 0
    ctypes.windll.user32.ShowWindow(ctypes.c_void_p(child), SW_HIDE)
    return not ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(child))


def window_height(hwnd: int) -> int:
    """取一个窗口的外框高度（像素）。取不到时返回 0。"""
    if not IS_WINDOWS or not hwnd:
        return 0
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rect = RECT()
        if not ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd),
                                                 ctypes.byref(rect)):
            return 0
        return max(int(rect.bottom - rect.top), 0)
    except (OSError, AttributeError):
        return 0


def remove_client_edge(hwnd: int) -> bool:
    """去掉原生控件的 ``WS_EX_CLIENTEDGE``（那个下凹的 3D 边框）。

    ## 为什么需要

    用户反馈："导航窗格的外框线……在深色主题下为什么仍旧保持白色？"

    实测（`tools/probes/probe_sash_border.py`）：``GenericDirCtrl`` 内层的
    ``SysTreeView32`` **带着 ``WS_EX_CLIENTEDGE``**——
    那是一条由 **Windows 按系统主题绘制**的下凹边框，
    ``SetBackgroundColour`` 对它完全无效，深色主题下就是一圈白框。

    ``wx.DIRCTRL_3D_INTERNAL`` 这个样式就是它加上去的。去掉之后
    边框由我们自己画（见 ``app._draw_pane_border``），颜色才可控。

    在**已经创建**的控件上改扩展样式也可以生效——``WS_EX_CLIENTEDGE``
    是绘制期读取的，不像 ``LVS_NOCOLUMNHEADER`` 那样只在创建时看一次。
    改完需要 ``SetWindowPos(SWP_FRAMECHANGED)`` 让它重算非客户区。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    GWL_EXSTYLE = -20
    SWP_FRAMECHANGED = 0x0020
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    user32 = ctypes.windll.user32

    # **`GetWindowLongW` 返回 0 有两种含义，必须分开。**
    #
    # 审计查出的缺陷：原来是
    #
    #     style = user32.GetWindowLongW(...)
    #     if not (style & WS_EX_CLIENTEDGE):
    #         return True          # "本来就没有，算成功"
    #
    # 而**调用失败时它也返回 0**。于是句柄失效时这里会
    # ``return True`` —— 报告"已经去掉了边框"，而实际什么都没做。
    # 调用方（`app._draw_pane_border`）会据此认为边框归自己画，
    # 结果就是**既没有系统边框、也没有自绘边框**（一片空白），
    # 而且没有任何报错。
    #
    # ## 怎么区分（两条一起用）
    #
    # ① **句柄必须先有效。** `IsWindow` 是最直接的判据，不依赖任何
    #    错误码机制。
    # ② 读样式用 `GetWindowLongPtrW`：64 位下 `GWL_EXSTYLE` 的**正确**
    #    入口是它，`GetWindowLongW` 在 64 位是遗留接口。
    #
    # ⚠️ **不要试图用 `SetLastError`/`GetLastError` 来判。**
    # 踩过：`ctypes.windll.user32.SetLastError` 根本不存在
    # （`AttributeError: function 'SetLastError' not found`）——
    # 它是 `ctypes.SetLastError`，而且需要 `use_last_error=True`
    # 加载 DLL 才会被 ctypes 捕获。为一个"判失败"引入这套机制不值得。
    if not user32.IsWindow(ctypes.c_void_p(hwnd)):
        return False                    # 句柄无效，如实说"没做成"

    def read_ex_style() -> int:
        """读扩展样式；优先用 64 位安全的 `GetWindowLongPtrW`。"""
        getter = getattr(user32, "GetWindowLongPtrW", None)
        if getter is not None:
            return int(getter(ctypes.c_void_p(hwnd), GWL_EXSTYLE))
        return int(user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE))

    style = read_ex_style()
    if not (style & WS_EX_CLIENTEDGE):
        return True                     # 真的本来就没有，算成功

    setter = getattr(user32, "SetWindowLongPtrW", None)
    if setter is not None:
        setter(ctypes.c_void_p(hwnd), GWL_EXSTYLE,
               style & ~WS_EX_CLIENTEDGE)
    else:
        user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE,
                              style & ~WS_EX_CLIENTEDGE)
    user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)

    return not (read_ex_style() & WS_EX_CLIENTEDGE)


def strip_column_header_style(hwnd: int) -> bool:
    """给列表控件加上 ``LVS_NOCOLUMNHEADER``，**让 Windows 根本不创建表头**。

    ## 为什么必须这么做（一次判断失误的记录）

    我们用自己的自绘表头（:class:`file_tracker.header.ColumnHeader`）顶替
    原生 ``SysHeader32``。原来的做法是"创建之后把表头隐藏掉"
    （``LVS_NOCOLUMNHEADER`` 事后设 + ``ShowWindow(SW_HIDE)``）。

    **那条路靠不住**：``Show()`` 会把藏好的表头重新显示出来，
    所以要在三处补藏（布局后、``CallLater``、``on_show``），
    而"补藏得逞了没有"取决于事件循环的时序。

    我一度用"深色主题下只数到一条顶栏"当作"没有双重顶栏"的证据——
    **那个证据是错的**：深色下表头因为反色 bug（白字浅底）根本看不见，
    所以双重顶栏被掩盖了，只有浅色才露出来。用户一句话点破了这一点。

    > **教训：拿"看不见"当"不存在"，等于把渲染 bug 当成了功能正确。**

    正确做法是**在样式层面就要求不创建表头**：``LVS_NOCOLUMNHEADER``
    只在控件创建时生效，所以必须**在 ``wx.ListCtrl`` 构造之前**把它拼进
    style（见 ``app.InitUI``），而不是事后 ``SetWindowLong``
    （实测事后设无效——Windows 已经建好了表头）。

    这个函数是给"已经创建、但想补救"的场景用的：设位之后强制
    ``SetWindowPos(SWP_FRAMECHANGED)`` 触发重建。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    GWL_STYLE = -16
    SWP_FRAMECHANGED = 0x0020
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
    user32.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE,
                          style | LVS_NOCOLUMNHEADER)
    user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
    native = find_child_window(hwnd, "SysHeader32")
    if native:
        # 已经建好的那个还得藏一次
        ctypes.windll.user32.ShowWindow(ctypes.c_void_p(native), 0)
    return True


# --------------------------------------------------------------------------
# 主题
# --------------------------------------------------------------------------

def system_uses_light_theme() -> bool:
    """读取系统"应用"深浅色设置。

    路径：``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize``
    的 ``AppsUseLightTheme``（1 = 浅色）。

    读不到时**返回 True（浅色）**：这是本项目历史上唯一实测过的主题，
    猜错方向时浅色至少是可读的（深色文字画在浅色底上）。
    """
    if not IS_WINDOWS:
        return True
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return bool(int(value))
    except (OSError, ValueError, ImportError):
        return True


def decode_accent_color(raw: int) -> tuple[int, int, int] | None:
    """把注册表里的 ``AccentColor``（**ABGR**，``0xAABBGGRR``）解成 ``(r, g, b)``。

    必须按字节拆，不能想当然地 ``>> 16 & 0xFF`` 取红——那样拿到的是蓝色。
    实测：Windows 默认蓝的 ``AccentColor`` 是 ``0xFFD77800``，
    正确结果是 ``(0, 120, 215)``。

    :return: ``(r, g, b)``；取不到有效颜色（全黑）时返回 ``None``
    """
    value = int(raw) & 0xFFFFFFFF
    red = value & 0xFF
    green = (value >> 8) & 0xFF
    blue = (value >> 16) & 0xFF
    if (red, green, blue) == (0, 0, 0):
        return None
    return (red, green, blue)


def system_accent_color() -> tuple[int, int, int] | None:
    """读取系统强调色，返回 ``(r, g, b)``；读不到返回 ``None``。"""
    if not IS_WINDOWS:
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\DWM"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        return decode_accent_color(value)
    except (OSError, ValueError, ImportError):
        return None


def get_dpi_for_window(hwnd: int) -> int:
    """窗口所在显示器的 DPI；不可用时回退 96。

    ``GetDpiForWindow`` 是 Windows 10 1607+ 的接口，老系统上取不到函数，
    此时返回 96 而不是崩溃。
    """
    if not IS_WINDOWS:
        return 96
    try:
        user32 = ctypes.windll.user32
        get_dpi = getattr(user32, "GetDpiForWindow", None)
        if get_dpi is None:
            return 96
        dpi = int(get_dpi(ctypes.c_void_p(hwnd)))
        return dpi if dpi > 0 else 96
    except (OSError, AttributeError):
        return 96


def apply_rounded_corners(hwnd: int, enable: bool = True) -> bool:
    """给窗口加 Win11 圆角（``DWMWA_WINDOW_CORNER_PREFERENCE`` = 33）。

    **必须在窗口显示之前调用**，否则会先闪一下直角边框。

    Windows 10 及更早版本上 ``DwmSetWindowAttribute`` 会返回非 0，属正常情况，
    此时不做任何处理即可——不要为了"统一"而在老系统上重试。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        DWMWCP_DEFAULT = 0
        preference = ctypes.c_int(DWMWCP_ROUND if enable else DWMWCP_DEFAULT)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return result == 0
    except (OSError, AttributeError):
        return False


def set_window_theme(hwnd: int, theme_name: str | None) -> bool:
    """给原生控件套一个视觉样式类（``uxtheme.SetWindowTheme``）。

    深色主题下用它给原生控件换成 ``DarkMode_Explorer``，
    这是**微软自己在资源管理器里用的做法**，比自绘可靠。

    :param theme_name: 样式类名；``None`` 表示"跟随系统"
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        uxtheme = ctypes.WinDLL("uxtheme")
        uxtheme.SetWindowTheme.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ]
        uxtheme.SetWindowTheme.restype = ctypes.c_long
        result = uxtheme.SetWindowTheme(ctypes.c_void_p(hwnd), theme_name, None)
        return result == 0
    except (OSError, AttributeError):
        return False


def find_child_window(hwnd: int, class_name: str) -> int:
    """在子窗口里按类名找一个后代窗口的句柄；找不到返回 0。

    用途很具体：``DataViewListCtrl`` 并没有暴露表头控件，但它的表头
    是一个真实的原生 ``SysHeader32``。要给它套深色样式，就得先把句柄找出来
    （实测层次：``wxWindowNR`` → ``wxDataView`` → ``wxWindowNR`` → ``SysHeader32``）。
    """
    if not IS_WINDOWS or not hwnd:
        return 0
    found = []

    def callback(child, _):
        try:
            name = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(ctypes.c_void_p(child), name, 256)
        except OSError:
            return True
        if name.value == class_name:
            found.append(child)
            return False
        return True

    try:
        EnumChildProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
        )
        ctypes.windll.user32.EnumChildWindows(
            ctypes.c_void_p(hwnd), EnumChildProc(callback), None,
        )
    except (OSError, AttributeError):
        return 0
    return found[0] if found else 0


def set_process_dark_mode(dark: bool) -> bool:
    """告诉 Windows：**本进程整体渲染深色控件**。

    这是深色主题里最关键的一步，也是我前几轮一直漏掉的。
    ``uxtheme.dll`` 有一个未公开但被广泛使用的导出
    ``SetPreferredAppMode``（序号 135）：

    * ``0`` = 默认（跟随系统）
    * ``1`` = 允许深色
    * ``2`` = **强制深色** —— 控件按深色绘制，**即使系统是浅色主题**

    调用它之后，**滚动条、列表表头、菜单、``MessageBox`` 这些由系统绘制的
    控件都会跟着变深**。不用它的话，`SetBackgroundColour` 对它们无效，
    深色主题下就会留下大片白底——用户反馈的"深色主题下的表现很差"就是这个。

    Windows 10 1809 之前的版本没有这个导出，此时返回 ``False``，
    调用方应退回逐控件设色。

    **必须在创建窗口之前调用**，之后调用对已经创建的控件不生效。
    """
    if not IS_WINDOWS:
        return False
    try:
        uxtheme = ctypes.WinDLL("uxtheme")
        # 优先按函数名取；它没有公开声明，取不到再按序号 135 取
        try:
            setter = uxtheme.SetPreferredAppMode
        except AttributeError:
            setter = uxtheme[135]
        setter.argtypes = [ctypes.c_int]
        setter.restype = ctypes.c_int
        # 2 = ForceDark：强制深色，不跟随系统
        setter(2 if dark else 0)
        return True
    except (OSError, AttributeError, TypeError):
        return False


def set_title_bar_dark(hwnd: int, dark: bool) -> bool:
    """让标题栏跟随深浅色主题（``DWMWA_USE_IMMERSIVE_DARK_MODE``）。

    编号先试 20（Windows 11），失败再试 19（Windows 10 build 18985 之前），
    **而不是假定机器版本**。与客户区不同，标题栏由 DWM 绘制，自绘客户区碰不到它；
    深色主题下不声明的话会有一条白色标题栏压在深色界面上。

    必须在窗口显示之前调用。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    value = ctypes.c_int(1 if dark else 0)
    for attribute in (20, 19):
        try:
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                return True
        except (OSError, AttributeError):
            continue
    return False


# --------------------------------------------------------------------------
# 窗口置顶
# --------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


def is_window_topmost(hwnd: int) -> bool:
    """窗口当前是不是置顶（读 ``WS_EX_TOPMOST`` 扩展样式位）。

    **这是唯一的判据。** ``wx.Frame.GetWindowStyle()`` 报的是 wx 自己的属性，
    不是 Windows 的实际状态——两者可以不一致，见 :func:`set_window_topmost`。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        ex_style = ctypes.windll.user32.GetWindowLongW(
            ctypes.c_void_p(hwnd), GWL_EXSTYLE,
        )
        return bool(ex_style & WS_EX_TOPMOST)
    except (OSError, AttributeError):
        return False


def set_window_topmost(hwnd: int, topmost: bool) -> bool:
    """置顶 / 取消置顶窗口（直接改 ``WS_EX_TOPMOST``）。

    :return: 操作后窗口的实际置顶状态

    ## ⚠️ 这里原来有一段**已过期**的说明，别再照着它改代码

    原文写着"**必须用 `SetWindowPos`，不能用 `wx.Frame.SetWindowStyle`**"，
    还附了一张表格说 `SetWindowStyle` 改不动 `WS_EX_TOPMOST`
    （"`GetWindowStyle()` 会骗你说变了"）。

    **那份结论和现在实测不符。**
    `tools/probes/probe_setwindowstyle_topmost.py` 三层读数一起验：

    ==============================================  ==================
    做法                                            ``WS_EX_TOPMOST``
    ==============================================  ==================
    ``SetWindowStyle(style | wx.STAY_ON_TOP)``      **真的变成 True**
    ``SetWindowStyle(style & ~wx.STAY_ON_TOP)``     **真的变回 False**
    ``win32.set_window_topmost(True/False)``        同样有效
    ==============================================  ==================

    wx 自己的 ``STAY_ON_TOP`` 位与 ``WS_EX_TOPMOST`` 是**同步**的，
    所以 `app.on_always_on_top` 用 `SetWindowStyle` 是**对的**。
    那张表格的结论当年也许是真（不同 wx 版本行为不同），
    但留着它只会让下一个人去"修"一个没坏的东西。

    ## 那这个函数为什么还留着

    两个理由，都不是"给 `on_always_on_top` 用"：

    * 它**不依赖 wx 的样式位**：`SetWindowPos` 直接置顶时
      ``GetWindowStyle()`` 不会跟着变（见上面探针的对照行），
      所以要"强制置顶但不动 wx 的记账"时只有它能做到。
    * `tools/verify_gui.py` 用它**读取**实际状态
      （`:func:`is_window_topmost`），那是判断"置顶真的生效了吗"的
      唯一可靠依据——不能用 wx 自己的说法去验 wx 自己的行为。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        target = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        ctypes.windll.user32.SetWindowPos(
            ctypes.c_void_p(hwnd), ctypes.c_void_p(target),
            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except (OSError, AttributeError):
        return is_window_topmost(hwnd)
    # 回读实际状态，而不是假定它成功
    return is_window_topmost(hwnd)
