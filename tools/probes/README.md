# 诊断探针

## 先读这两条：本环境的"看图"结论**大半不可信**

用户多次说"你自己看"，我就是在这里反复栽跟头。**结论先摆出来**：

### ① 窗口抓图在这个环境里不可靠

| 方式 | 结果 |
|---|---|
| `WM_PRINTCLIENT` | 全黑 |
| `PrintWindow(hwnd, hdc, 0)` | **本进程**窗口能拿到标题栏，但**客户区正文丢失** |
| `GetDC(hwnd)` + `GetPixel` | 返回值自相矛盾（同一段文字在每个 y 都"出现"，按钮位置读到纯白） |
| `ScreenDC` + `Blit` | 抓到的是**别的窗口**（本进程窗口没被合成） |
| `wx.WindowDC` / `wx.ClientDC` + `Blit` | 只在**刚建好、已验证为纯色**的窗口上可信 |
| **`PrintWindow` 打在⚠️子控件⚠️上** | ✅ **可信**（见下） |

#### ✅ 例外：`PrintWindow` 打在**子控件**上能得到真画面

上面第 2 行说的是"打在**顶层 Frame** 上" —— 那样确实只拿到标题栏、
客户区全白。但**打在 `wx.ListCtrl` 这类子控件上**时，
控件会把自己的内容**完整重画**进给定 DC，拿到的是**真像素**。

实测校准（`probe_printwindow_capture.py`、`probe_row_paint_pixels.py`）：
把某行涂成纯红 `#FF0000`、另一行涂成纯绿 `#00FF00`，抓回来
**就是红和绿**（各占 92% 像素）。

**用它的三条规矩**（少一条结论就不可信）：

1. **必须打在控件上，不要打在 Frame 上** —— 打 Frame 时子控件不被递归画
2. **抓之前先 `Refresh()` + `Update()`** —— 否则拿到的是上一次的画面
3. **坐标用该控件的客户区坐标**（`GetItemRect(row)` 就是），不要混屏幕坐标

> ⚠️ 另外两个害过人的坑（都实测过）：
>
> * **`wx.ScreenDC` + `Blit` 读不到本进程窗口的真实合成结果** ——
>   涂成纯红的行，从屏幕抓回来仍是 `#FFFFFF`。**别用屏幕采样判颜色。**
> * **`wx.GetMousePosition()` 是全局真实鼠标**，而 `on_list_motion` 会
>   按它改行底色。探针里每 `YieldIfNeeded()` 一次就可能投递一次
>   `WM_MOUSEMOVE`，于是**测试自己把刚涂的颜色改回主题色**。
>   量颜色之前先把鼠标挪开（`SetCursorPos`）。

**所以判断"画得对不对"要用另外两条路**：

1. **位图上重画**（`probe_layout_render.py`）——
   把窗口按 Layout 的几何画到自建 `wx.Bitmap`，再数暗像素。
   位图上的 `GetPixel` 是可靠的。
2. **拦截绘制调用**（如拦 `wx.DC.DrawLine` 看有没有落笔）。

（第 3 条是后来才找到的、最直接的一条：**`PrintWindow` 打在子控件上** ——
见上面那个例外小节。）

> 我因为轻信抓图，得出过两次错误结论：
> "三种 DC 都画不出正文"（其实画得出来）、"导航窗格白边 2 像素"（其实取样不可信）。

### ② 对同一块 `wx.Bitmap` 开两个 `wx.MemoryDC`，位图会被搞坏

`probe_layout_render.py` 第一版先开一个 DC 画正文、再开一个画按钮，
结果**正文被丢掉**，看上去像"正文画不出来"。
**一个 DC 画到底**；要偏移就用 `dc.DrawBitmap` 贴。

---

**这些不是构建流程的一部分，也不会在 CI 里跑。** 它们是"当时是怎么知道的"的存档。

每一个都对应一条写在源码或开发日志里的结论。**删掉它们，下一个人会把同一条路
再走一遍**——尤其是 `probe_lvm_final.py` 与 `probe_native_lvm.py` 对应的那条：
"频次列居中"为什么没有走原生 `LVM_SETCOLUMN`。

用法都是：

```bash
python tools/probes/<名字>.py
```

部分是**会开窗口**的（见下），跑完自己销毁；它们不修改仓库里的任何文件。

---

## 分类索引：我现在该跑哪个？

**按用途分组。** 每组第一列是"什么时候用它"。
详细结论在下面的同名小节里（本文档其余部分是**逐条的实测记录**，不重复在这里）。

### 一、抓图与离屏渲染 —— 先解决"怎么看到像素"

| 探针 | 什么时候用 |
|---|---|
| `probe_capture.py` | 想知道本进程内**哪种抓图方式能拿到真像素**（先跑它） |
| `probe_layout_render.py` / `probe_settings_render.py` | 把弹窗**离屏重画成图片**看排版 |
| `probe_render_noise.py` | 想确认"**像素能不能当判据**" |
| `probe_dim_image.py` | 量某张图的尺寸/内容 |

> ⚠️ **本环境的窗口抓图大半不可信** —— 见下面的「先读这两条」。

### 二、列表：行高与间距

| 探针 | 什么时候用 |
|---|---|
| `probe_row_spacing.py` | 怀疑 `LVM_SETITEMSPACING` 生效了（**它不生效**） |
| `probe_row_height.py` | 改"空图列表托底"那套行高机制之前 |
| `probe_row_ratio.py` | 改 `METRICS.row_ratio`（两个窗格的比例）之前 |
| `probe_row_effect.py` | 改完行高后，**核副作用**（文字有没有位移、数据缺没缺） |

### 三、列表：高亮 / 悬停 / 选中

`probe_row_hover.py` · `probe_row_selected_pixels.py` · `probe_row_highlight.py` ·
`probe_row_colour_set.py` · `probe_row_trackselect.py` · `probe_two_tier_highlight.py` ·
`probe_hover_time.py` —— **动"预选 / 选中"这两档之前，全部跑一遍**。

### 三之一、⚠️ "存着蓝、看着灰" —— 先读这一节，再动手

用户报「从导航窗格打开之后，记录列表那条是**浅灰**而不是蓝色」。
前十轮全部**方向错了**，错在两点，都值得记下来：

#### 错误一：拿"存了什么"当"画成什么"

```python
ctrl.GetItemBackgroundColour(row)     # → 永远是 #0078D7
```

**这个读数与屏幕上画成什么无关。** 七个探针全绿、用户始终看到灰，
根子就在这儿。判"画得对不对"必须看像素，而**本环境里能信的是
`PrintWindow` 打在列表控件上**（见上面「先读这两条」的例外那条）。

#### 错误二：探针复刻的是"我以为的场景"

差一点的地方全是**配置口径**，不是代码：

| 我以为 | 实际（`%APPDATA%\File Tracker\config.json`） |
|---|---|
| 按频次降序排 | **`"sort_column": "path"` 升序** |
| 视角在顶上 | `v_relative: 0.333`（中间） |
| 走 `on_open` | 可能走 `on_dir_item_activated`（树里双击**文件**） |

**排序口径决定"新记录落在第几行"**，也就决定了它是否在屏幕上。
用错口径，量到的永远是另一条记录。

| 探针 | 什么时候用 |
|---|---|
| `probe_row_paint_pixels.py` | **首选**：从导航窗格打开后，量选中那行**真正被画成**什么色（含仪器自校准） |
| `probe_printwindow_capture.py` | 先确认 `PrintWindow` 在本机拿得到真像素（涂红/绿自校准） |
| `probe_paint_order.py` | 记录"改底色 / 改选中 / 重画高亮"三件事的**先后顺序**（判断蓝色有没有画在选中之后） |
| `probe_pixel_coords.py` | 怀疑采样坐标算错时跑（含"鼠标污染"的现场演示） |
| `probe_user_shape.py` | 用**用户配置的形状**（path 升序 + 视角居中）复现 |
| `probe_focus_bit_pixels.py` | 单变量对照：只差原生 `FOCUSED` 位，看画出来有没有区别 |
| `probe_real_open_pixels.py` | **真的**启动资源管理器（不换桩）后，看激活状态与画面 |
| `probe_inactive_selection.py` | **未激活窗口里选中行画成什么色**（实测 `#F0F0F0`，Windows 自己的非活动选中色） |
| `probe_tree_dblclick_focus.py` | **双击导航窗格里的文件**之后焦点/选中对不对（与「打开」按钮**并排比**） |
| `probe_real_dblclick.py` | **发真的鼠标消息**测双击（不碰事件绑定，只看行为）——**首选** |
| `probe_tree_events.py` | 真双击时 wx **到底发哪些事件**（实测：`EVT_TREE_ITEM_ACTIVATED` **不发**） |
| `probe_pathbar_enter_focus.py` | **地址栏输入路径 + 回车**之后焦点/选中对不对 |
| `probe_paint_invariant.py` | 钉住不变量：选中行变了 ⇒ **必须被上过色**，且账本同步 |
| `probe_multiselect_feature.py` | **多选功能总验证**（Ctrl 点选 / 拖拽 / 右键两项 / 多选打开 / 多选删除）——**改多选之前先跑** |
| `probe_multiselect_native.py` | 多选可行性：**必须清原生 `LVS_SINGLESEL`**（只改 wx 侧无效） |
| `probe_multiselect_drag.py` | 拖拽框选为什么**原生不可用**（7 种组合全试过，都只选中一行） |

### ⚠️ 多选相关的三条硬结论（改之前先读）

1. **`LVS_SINGLESEL` 必须清"原生"那一位。**
   `ctrl.SetWindowStyleFlag(...)` 只改 wx 侧 ⇒ API 多选能用、
   **真 Ctrl 点击仍只选一行**。用 `win32.enable_list_multi_select()`。

2. **原生拖拽框选不可用**，7 种组合（`MK_LBUTTON` 有无、步数/延时、
   `SetCapture`、预先选中起点、`LVS_EX_DOUBLEBUFFER`、混合）
   **每一种都只选中按下那一行** ⇒ 拖拽是应用**自己实现**的
   （见 `app.on_list_left_down` / `_handle_drag_motion` / `_select_range`）。

3. **判断"左键还按着"要用 `event.LeftIsDown()`，不能用 `wx.GetMouseState()`。**
   后者读的是**系统级真实鼠标**，`SendMessage` 发的 `WM_MOUSEMOVE` 不改它 ⇒
   拖拽第一帧就被判成"左键已松开"、整段拖拽跑不起来。

### ⚠️ `_focus_pane` 是"闸门变量"：每个入口都要有人给它赋值

`record_accessed_path` 里"给记录列表焦点 + 换选中"整块由 `from_tree` 把关，
而 `from_tree` 看的是 `_focus_pane`。**这个变量有 4 个入口**，
少写一个那个入口就整块失效（用户已经报回来**两次**）：

| 入口 | 谁设 `_focus_pane` |
|---|---|
| 地址栏回车 `on_path_submitted` | 显式 `= "tree"` |
| 双击树里的文件 `on_dir_item_activated` | 显式 `= "tree"` |
| 双击列表 / `on_open_selected` | 双击前的 `EVT_SET_FOCUS` → `"list"` |
| 「打开」按钮 `on_open` | 树的 `EVT_SET_FOCUS` → `"tree"` |

**改任何一个入口之前，先把上表数一遍** —— 靠"上一个事件顺手设了"是隐式契约。

### ⚠️ 一个容易写反的预期：`_focus_pane` 的**终态**

双击导航窗格里的文件之后，`_focus_pane` **最后是 `'list'`，不是 `'tree'`** ——
那是**正确的**：

```
① on_dir_item_activated 设 _focus_pane = "tree"   ← 让 from_tree 为真
② record_accessed_path 里 SetFocus() + 上色
③ SetFocus() 触发 EVT_SET_FOCUS → on_list_selection_made
   → _focus_pane = "list"                          ← 正确的终态
```

`_focus_pane` 的语义是"**用户最后一次在哪里操作**"，而此刻焦点**确实**
已经在记录列表上了。写探针时要把"过程中的意图"和"终态"分开，
否则会像我第一版那样把对的判成错的。

> ⚠️ 这几个探针里有**两处必须照做的动作**，否则读数无意义：
> 抓图前 `Refresh()`+`Update()`、采样前把鼠标挪出列表（见上文两条坑）。

### ✅ 装进程序里的仪器：`FT_DEBUG_PAINT`

探针复刻不了用户的环境，所以**仪器要装进程序本身**，让他跑一次。

**推荐：文件开关**（不依赖启动方式，一眼能看出开着没有）：

```powershell
# 开
New-Item "$env:APPDATA\File Tracker\enable-paint-trace" -ItemType File
cd "D:\Coding\MyGitHub\File-Tracker"
.\run.ps1
# 复现一次（从导航窗格「打开」或双击文件），然后关窗口
# 关掉诊断：删掉那个文件
```

也可以用环境变量（两者任一即可）：`$env:FT_DEBUG_PAINT = "1"`

> ⚠️ **2026-10-17 实测的坑**：用户设了 `$env:FT_DEBUG_PAINT = "1"` 再跑 `run.ps1`，
> 而 `[PAINT]` **一行都没出来**。同一个 PowerShell 里查：
> `python -c "import os; print(os.environ.get('FT_DEBUG_PAINT'))"` → **`None`**。
> **那个 `python` 不是 `run.ps1` 用的解释器，环境变量没进到被测进程。**
> ⇒ **开诊断不能依赖某一条特定启动路径**，所以补了文件开关。
> 另外 `on_close` 不是唯一的退出路径（关控制台 / Ctrl+C 都不走它），
> 所以还有 `atexit` 兜底 —— 两条都有探针验证：`probe_file_switch.py`。

**装上时会自报一行**（这一行不能省，否则"到底装没装上"查不出来）：

```
[PAINT] 行底色记录器已装上（开关 = 文件开关 …；已包装 6 个方法：…）
```

报告落在 `%APPDATA%\File Tracker\paint-trace.txt`，里面是**每一次**外观改动的
"最后归属"：`(行, 颜色)` + **调用栈** + 当时的焦点/激活/选中/顶行，
外加三个记忆账本（`_paint_key` / `_highlighted_row` / `_hover_row`）。

**报告末尾有「一句话结论」，不用自己读完整张清单**：

```
── 一句话结论 ──
  选中行 30 **最后一次被写成系统高亮蓝**（app.py:2434 _apply_selection_highlight）。
  若屏幕上仍是灰 ⇒ **问题在程序之外**（窗口未激活 / 被遮挡 / 另一处覆盖）。
```

可能的三种结论：

| 结论 | 含义 |
|---|---|
| 最后写成 `row_hover` | 屏幕上就是浅灰，**调用栈里的函数就是元凶** |
| 最后写成系统高亮蓝 | 程序画对了 ⇒ **问题在程序之外**，别再改配色 |
| 选中行没有任何改动记录 | 那行根本没被上过色（重建时的底色留下来了） |

`probe_report_demo.py` 可以**不开窗口**地演示这份报告长什么样。
`probe_file_switch.py` 验证文件开关 + 退出兜底（8 条）。

### 三之二、列表：刷新时的**视角、选中、闪烁**

用户报"双击打开一条之后，记录窗格又回到最开头了"时写的三个探针。
**改 `_render_rows` 之前先跑它们。**

| 探针 | 什么时候用 |
|---|---|
| `probe_open_anchor.py` | **重放真实的双击流程**，把每次 `_remember_view()` / `_render_rows()` 的中间状态打出来。**"锚点取晚了"和"重复记锚点"都是它抓到的** |
| `probe_scroll_anchor.py` | **新旧对比**：同一场景分别用 `Focus()` 与 `SetItemState()`，看哪个会把视角滚走 |
| `probe_doublebuffer.py` | 想问"要不要加双缓冲"时先跑它 |

### ⚠️ 改"刷新时保持视角"必须知道的四件事

都是实测踩出来的，**顺序就是踩坑的顺序**：

1. **锚点必须在 `self._rows` 换掉之前取** —— 否则是"旧的视觉行号 + 新的记录列表"
2. **`_remember_view()` 必须幂等** —— 它会被调用多次，第二次时 `_rows` 已经换了
3. **`Focus()` 会把视角滚走** —— 设焦点要用 `SetItemState`，不用 `Focus()`
4. **`Freeze()` 里不能读写滚动状态** —— 冻结期间 `GetTopItem()` 返回旧值、
   `ScrollLines()` 不生效。**`Freeze` 只包"重建"，选中与回位放到 `Thaw` 之后**

> **判据**：`Freeze` 里只允许**改内容**，不允许**读滚动状态**。

### 四、列表：多选 / 双击 / 焦点

| 探针 | 什么时候用 |
|---|---|
| `probe_multi_select.py` | 问"列表到底能不能多选" |
| `probe_multiselect.py` | 问"**多选树上** `SelectItem` 的语义"（**与上一个是两个探针，别合并**） |
| `probe_double_click.py` | 改了列表标志之后，核双击语义有没有变 |
| `probe_open_focus.py` | 核「打开」到底跟不跟最后一次选中 |

### 五、表头

`probe_header_event.py` · `probe_native_lvm.py` · `probe_lvm_final.py` ·
`probe_darkmode_api.py` —— **改表头之前跑**。结论：原生表头在深色下不可用，
所以本项目是自己画的（见「双重顶栏」那节）。

### 六、树与导航窗格

| 探针 | 什么时候用 |
|---|---|
| `probe_dir_tree.py` | 改 `dir_tree.DirectoryTree` 之前（图标尺寸、盘符、`GetPath`） |
| `probe_tree_paths.py` | 怀疑**盘符解析错了**（`C:` vs `C:\\` 那类） |
| `probe_tree_perf.py` | 改 `_children_of` / `_populate_item` 之前**先量基线** |
| `probe_lazy_expand.py` | 核树是不是懒加载的 |
| `probe_tree_labels.py` | 核驱动器节点的标签（`SYSTEM (C:)` 那种） |
| `probe_tree_frame.py` / `probe_tree_scrollbar.py` / `probe_tree_blank.py` | 核容器底色 / 滚动条 / 空白区 |
| `probe_nav_variants.py` | 查那圈白框的根因（**已结案**，留作参考） |

### 七、布局 / 字体 / 弹窗

| 探针 | 什么时候用 |
|---|---|
| `probe_retheme_twice.py` | 改**设置窗口的"所见即所得"**之前必跑：量"预览/确定"两阶段各重上色几次（真实对话框 + 定时器自动点按钮） |
| `probe_system_theme_watch.py` | 改 `on_activate` 里"跟随系统才重读注册表"那一段之前必跑：验证挂起期间的系统主题变化**不会丢** |
| `probe_dialog_fonts.py` | 核**弹窗字号**与**导航窗格行高** |
| `probe_nav_fonts.py` | 核导航窗格里每一处文字的字号 |
| `probe_settings_font.py` | 核设置窗口的标签会不会被按钮压住 |
| `probe_stroke_raster.py` | **定规则**：GDI+ 的描边落在哪几列（改描边前必读） |
| `probe_button_border.py` / `probe_button_edge_columns.py` | 核按钮描边有没有被裁断 |
| `probe_sash_border.py` / `probe_sash_geometry.py` / `probe_sash_drag.py` | 改两栏分界线之前 |
| `probe_dialog_center.py` / `probe_dpi_units.py` | 核居中 / 核 wx 报的坐标单位 |

### 八、性能与体积

| 探针 | 什么时候用 |
|---|---|
| `probe_perf_baseline.py` | **分档量每个操作的耗时**（200/1000/3000/6000 行），看增长倍数是否超线性 —— **优化之前先跑它** |
| `probe_perf_detail.py` | 把"重建"**逐项拆开**（哪种原生调用多少次、各占多少）—— 优化只能从"减少调用次数"入手 |
| `probe_insertitem_overload.py` | `InsertItem` 的**多列重载**能不能用（**实测不通**，见下） |
| `probe_bundle_size.py` / `probe_pyz_contents.py` / `probe_size_candidates.py` / `probe_libcrypto_source.py` / `probe_used_modules.py` | 每轮体积审计 |

#### 2026-10-17 的性能结论（改之前先读）

**优化过的（改前 → 改后，6000 行）：**

| 操作 | 改前 | 改后 | 手法 |
|---|---|---|---|
| 拖拽一帧 | 888.8 ms | **4.7 ms** | 差集法：只改和上一帧不同的行 |
| 重建 | 1180–1195 ms | **626–791 ms** | `GetColumnWidth` 3004→**5** 次、`GetTextExtent` 6604→**605** 次（都是缓存） |
| 删除 20 条 | 4095 ms | **2138–2804 ms** | 去掉冗余的全清 |

**剩下的下限在哪**：重建的 ~626 ms 主要是 `SetItem` 18000 次 +
`InsertItem` 6000 次 + `SetItemBackgroundColour` 6000 次，**全是跨语言原生调用**。
虚拟列表（`LC_VIRTUAL`）能根治但**不支持逐项底色**，而本项目的高亮全靠它
—— 所以在这个架构下已接近下限。

**试过不通的路**（别重走）：

* `wx.ListCtrl.InsertItem(row, text, imageIndex, values)` 的**多列重载**
  在 wxPython 4.2.2 里**四个重载全不匹配** —— wx 没暴露它。
  所以每行那 3 次 `SetItem`（频次/日期/时间）**省不掉**。

| 探针 | 什么时候用 |
|---|---|
| `probe_rebuild_cost.py` / `probe_scale_cost.py` / `probe_scale_profile.py` | 改列表重建逻辑之前**先量基线** |
| `probe_adjust_reentry.py` | 怀疑某个回调被重复进入 |
| `probe_bundle_size.py` / `probe_pyz_contents.py` / `probe_size_candidates.py` / `probe_libcrypto_source.py` / `probe_used_modules.py` | 每轮体积审计 |

### 九、一次性诊断（结论已并入代码，留着当模板）

| 探针 | 它解决过什么 |
|---|---|
| `probe_theme_icon.py` | **自绘按钮"看着没画出来"** —— 渲染成位图数像素，一次定案 |
| `probe_submit_hang.py` | **界面卡死** —— `faulthandler` 超时转储调用栈 |
| `probe_standardpaths_hang.py` | 同类卡死（`wx.StandardPaths`） |
| `probe_field_edge.py` | 排除了 `WS_EX_CLIENTEDGE`（**结论：不是它**） |
| `probe_dataview_api.py` / `probe_topmost.py` / `probe_setwindowstyle_topmost.py` | API 可行性 |
| `probe_version_info.py` / `probe_sort_persistence.py` / `probe_pathbar_focus.py` / `probe_item_colour.py` | 版本资源 / 排序持久化 / 地址栏 / 按列设色 |

> **`probe_theme_icon.py` 与 `probe_submit_hang.py` 值得当模板**：
> 前者回答"自绘的东西到底画了没有"，后者回答"到底卡在哪一行"。
> 这两类问题**读代码都看不出来** —— 本会话三次读代码失败，都是它们定的案。

### 十、试过但**不通**的路

见本文件后面的「试过但**不通**的路」那节 —— **改相关的代码之前先读它**，
免得把死路再走一遍。

---

## ⚠️ 写新探针前必读：临时目录一律用 `_probe_temp`

用户反馈过："**你怎么每次打开的测试窗口都不关，我桌面上一堆 target-folder**"。

查下来是两个原因叠加，都已修：

① 验证脚本走"地址栏回车"那条路时会调到**真的** `open_folder`，
   每跑一次就在桌面上开一个资源管理器窗口；那些窗口还会**占住临时目录**，
   让清理失败，目录就留在盘上。

② 各个探针用 `tempfile.mkdtemp()`（**不带清理**），跑一次留一个。
   实测 `%TEMP%` 下积了 19 个 `probe-*` / `shot-*` 目录。

**规矩**：

* 探针一律 `with probe_temp("probe-xxx") as scratch:`，不要用裸 `mkdtemp`
* 任何"会打开资源管理器"的路径，必须先把 `frame.open_folder` 换成替身：
  `_probe_temp.open_in_explorer_stub(record)`
* 清理失败要**打印出来**，不要 `except: pass`——那又变成"靠我记得去清"

---

## `probe_tree_blank.py` — 目录树的空白区为什么点不中

会开窗口。量"最后一个可见条目的底边"与"客户区高度"的差。

**结论：条目下方确实有一块真空白，而 `SysTreeView32` 在那里点击
不会选中任何节点——这是原生行为，不是缺陷。**
（资源管理器也一样：点文件夹列表下方的空白不会选中文件夹。）

实测：最后一条底边 y=811，客户区高 830 → **下面 19 像素是空白**。

**所以不去"修"它**——加一个假的点击行为只会与系统不一致。
能改善的是**选中状态不够显眼**，于是给树加了
`wx.TR_FULL_ROW_HIGHLIGHT`（选中项铺满整行，与 Win11 资源管理器一致）。

## `probe_capture.py` — 本进程内哪种抓图方式能拿到真像素

会开窗口。抓一个**整块纯红**的窗口，看中心像素是不是 `(255,0,0)`。

**结论**（判据明确，不是"看起来像"）：

| 方式 | 结果 |
|---|---|
| `wx.WindowDC` + `Blit` | ✅ 拿到真像素 |
| `wx.ClientDC` + `Blit` | ✅ 拿到真像素 |
| `PrintWindow(hwnd, hdc, 0)` | ✅ 在这个纯色窗口上拿到了 |
| `wx.ScreenDC` + `Blit` | ❌ 拿到别的窗口 |

**注意**：`PrintWindow` 在**纯色**窗口上与其它方式一致，但在**有内容的
对话框**上会丢客户区正文——所以它是"能过纯色测试、却在真实窗口上骗人"。
**别只看它通过了就信它。**

## `probe_layout_render.py` — 把弹窗离屏重画成图片

> **注意这个探针自己也有坑，两条都踩过：**
>
> 1. **别对同一块 `wx.Bitmap` 同时开两个 `wx.MemoryDC`**——位图会被后者接管，
>    先画的内容丢掉。一个 DC 画到底；要偏移用 `dc.SetDeviceOrigin`。
> 2. **读位图之前先 `dc.SelectObject(wx.NullBitmap)`** 把它摘下来。
>    在位图仍被 DC 选中时读/存，结果不可靠。
>
> 这两条都会让图看起来像"正文没画出来"，而**实际实现是好的**——
> 我又因此白跑了一轮。判断"实现有没有问题"时，
> 先用一个**已知能画的**对照（这里是直接 `_draw_body` 到位图，
> 实测 48 个暗像素），再怀疑实现。


不开真实交互，把弹窗按 Layout 的几何**画到自建位图**，输出
`_shots/layout-{light,dark}.png`，并数正文区的暗像素作为**正向证据**。

**这是本环境里唯一可信的"看外观"手段。** 用途：

* 核对 Roboc 公式算出来的几何（margin 42、按钮右对齐、96×32 → 168×56）
* 确认正文**真的画得出来**（不是"矩形算得对"）
* 对比浅色/深色两套配色

`RoundedButton.draw_to(dc, w, h)` 就是为它抽出来的——
`_on_paint` 现在也走这一条，保证"屏幕上看到的"和"这里核对到的"是同一段代码。

## `probe_row_hover.py` / `probe_row_selected_pixels.py` / `probe_row_highlight.py` / `probe_row_colour_set.py` / `probe_row_trackselect.py` — 列表行的悬停与选中

用户反馈："深色主题有鼠标预选跟随，浅色主题没有。
也可能是浅色主题下的鼠标预选跟随提示色被设置成了纯白。"

**这一组探针的价值主要在于"排除"，而不在于"看出来"：**

| 探针 | 结论 |
|---|---|
| `probe_row_hover.py` | 列表**没有任何 hover 实现**；`TRACKSELECT` 没开；系统高亮 = `#0078D7` |
| `probe_row_selected_pixels.py` | 选中一行后**底色完全不变**（浅色 `#FFFFFF`、深色 `#242424`，与未选中一模一样） |
| `probe_row_highlight.py` | ❌ **不可信**：四个不同状态读回一模一样的像素图案 |
| `probe_row_colour_set.py` | ✅ 用**属性回读**：显式设高亮色**保得住**，取消选中也能还原 |

**根因**：每行都被 `SetItemBackgroundColour` 显式设过，
**原生选中高亮就不画了**——所以两个主题其实都没有高亮，
差别只是纯白文字在深色底上更跳，看着像"跟随"。

**修法**：接 `EVT_LIST_ITEM_SELECTED/DESELECTED`，自己把选中行设成
`SYS_COLOUR_HIGHLIGHT`；悬停则开 `LVS_EX_TRACKSELECT`。

**`probe_row_trackselect.py` —— 结论被推翻两次，留作教训。**

它当时测出"`LVS_EX_TRACKSELECT` 可以单独打开、没有副作用"，
我就据此采用了它。**但标志选错了**：

* `LVS_EX_TRACKSELECT` = 悬停一段时间后**自动选中**
  （带定时器 → 用户实测"反应特别慢，有近一秒的延迟"）
* `LVS_EX_TWOCLICKACTIVATE` = "highlighted but not selected"（真正的预选语义）

换成 `TWOCLICKACTIVATE` 之后，用户实测**浅色主题依旧没有预选**
（深色有）——原生热跟踪的绘制**随主题而变**，第三方既拿不到
也改不了那个颜色。

**最终结论：不要依赖原生热跟踪，自己画。**
见 `probe_two_tier_highlight.py` 与 `theme.row_hover`。

**这个探针的教训**：它证明了"能不能开"，却没证明"该不该开"。
检查副作用 ≠ 检查语义是否匹配需求。

> ⚠️ **悬停是热跟踪，`SendMessage(WM_MOUSEMOVE)` 模拟不出来**
> （实测：投递之后 `LVIS_DROPHILITED` 仍是 False）。
> 所以自动化只能验证"样式位开了、且没副作用"，
> **真正的悬停观感必须人眼确认**。

## `probe_hover_time.py` — 悬停延迟是多少、能不能调

**关键数字（本机实测）**：系统默认悬停时间
`SPI_GETMOUSEHOVERTIME` = **100 ms**，列表 `LVM_GETHOVERTIME` = 0
（0 = 未设 → 取系统默认）。

⚠️ **这个探针的 `LVM_SETHOVERTIME` 回读是坏的**（恒为 0）。
原因是 ctypes 没声明签名——

```python
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p]
user32.SendMessageW.restype = ctypes.c_void_p
```

不声明时返回值按 32 位整数解释，长消息**静默截断**。
我差点据此得出"这个 API 不可用"的错误结论。

## `probe_double_click.py` — 加了标志之后双击语义有没有变

投递真实的 `WM_LBUTTONDOWN` / `WM_LBUTTONUP` / `WM_LBUTTONDBLCLK`，
数 `on_item_activated` 被调了几次。

**实测：3 次双击 → 3 次激活；单击之后选中项 = 0（只选中、不打开）。**
所以 `LVS_EX_TWOCLICKACTIVATE` 只带来热跟踪，没改双击语义。

**两条踩过的坑（探针里都防了）**：

1. `SendMessageW` 必须显式声明签名（见上）。
2. **探针会真的把资源管理器弹出来**：`on_item_activated` 里有
   `_open_in_explorer`（**静态方法**）和
   `wx.CallLater(..., reset_dir_ctrl_scroll)`——
   只在实例上改 `frame.open_folder` **挡不住**，
   实测探针挂死 240 秒、临时目录被锁。
   正确做法是把所有出口都堵上，并加线程超时。

## ⚠️ `probe_multi_select.py` 与 `probe_multiselect.py` 是**两个**探针，别合并

名字只差一个下划线，很容易以为其中一个过时了。**不是**——它们查的是
**两个不同的控件**，而且回答的是不同的问题：

| 探针 | 查什么 | 结论 |
|---|---|---|
| `probe_multi_select.py` | **记录窗格**（`wx.ListCtrl`）能不能多选 | `LVS_SINGLESEL` 开着 ⇒ 单击只能选中一行 |
| `probe_multiselect.py` | **导航窗格**的树（`GenericDirCtrl`）上 `SelectItem` 的语义 | 多选树上它是"追加"，所以必须先 `UnselectAll` |

合并它们只会让"哪一个说的是哪个控件"变模糊。留下这个说明是为了让下一个人
不去做那次合并。

## `probe_multi_select.py` — 列表到底能不能多选

用户的反问："我有没有骗你，你查代码里是否支持多选就知道了。"

**实测**：`LVS_SINGLESEL` 在样式 `0x00202820` 里**没有**，
但 wx 的 `LC_SINGLE_SEL` 是 **True**——`wx.ListCtrl` 加 `wx.LC_REPORT`
时 wx 自己带的。真按 Ctrl 点两行：`GetSelectedItemCount() = 1`。

**结论：是单选。** 所以"两条高亮"**不是两条选中**。

> 这个探针真正的价值是**推翻我的一个错误推理**：
> 我拿"选中行底色不变"去否定"用户看到了两条高亮"——
> 那个推理越界了。两条高亮确实存在，只是成因不是多选。

## `probe_two_tier_highlight.py` — 两档高亮（预选 / 选中）逐项验证

会开窗口，**跑两个主题各一遍**。判据用**属性回读**，不用像素。

通过 `frame._set_hover_row(row)` 直接驱动悬停（那是 `on_list_motion`
唯一的出口，绕开"模拟真实鼠标"这件做不到的事），然后读
`GetItemBackgroundColour(row)`。

**实测结果（浅色 / 深色都成立）**：

| 场景 | 浅色 | 深色 |
|---|---|---|
| 初始 | 全 `#FFFFFF` | 全 `#242424` |
| 悬停行1（不选中） | 行1 = `#DCE9F7` | 行1 = `#2B4A66` |
| 悬停行1 + 选中行3 | `#DCE9F7` / `#0078D7` | `#2B4A66` / `#0078D7` |
| 悬停到已选中行 | 仍是 `#0078D7`（选中优先） | 同 |
| 鼠标离开 | 行1 还原 `#FFFFFF` | 行1 还原 `#242424` |

## `probe_dialog_center.py` — 提示窗内容是不是真的居中了

会开窗口，跑三个场景（单行 / 多行 / 超长折行）。

**判据是几何，不是像素**：用 `dc.GetTextExtent(line).width`（与
`_draw_body` 同一个来源）算出每行会画在哪，再比左右留白。

**实测**：三个场景的正文左右留白差都 **≤ 1 px**（取整误差），
按钮组也居中；超长消息的正文高正好装进正文区（说明测量没跑偏）。

> 顺带记一个判据设计的坑：**"左右留白相等"不能单独用**——
> 整篇都是空行时它也成立。所以另加了一条
> "正文确实有内容（最宽一行 > 0）"的阳性对照。

## `probe_button_border.py` — 按钮描边有没有被裁断 + 圆角半径

用户："按钮边缘线右侧有被裁断痕迹，roboc 里是没有这种情况的。"

**根因**：`DrawRoundedRectangle(0, 0, w, h, r)` 画的是**路径**，
1px 描边以路径为中心向两侧各扩 0.5，于是右边界线覆盖
`[w-0.5, w+0.5)` 而客户区只有 `[0, w)`——**外半像素被裁掉**。

**判据**：把按钮画到**位图**上（位图的 `GetPixel` 在这个环境可信），
比较最外一圈四条边的颜色。被裁的那条会明显更接近底色。

**实测（修后）**：`{'左': 237, '右': 237, '上': 237, '下': 237}` 四条一致。

> 这个探针还量了圆角半径随高度的比例，用来核对"统一参数"。

## `probe_stroke_raster.py` — **定规则**：GDI+ 的描边到底落在哪几列

这张表是这轮最有用的产出。把各种 `(inset, 矩形宽)` 组合都画到
纯白位图上（只描边、不填充），量出墨迹所在的最左/最右列：

| inset | 矩形 | 左列 | 右列 | 结果 |
|---|---|---|---|---|
| 0 | 189×42（=位图尺寸） | 0 | **无** | ❌ 右支完全落在位图外 |
| **0** | **188×41** | **0:255** | **188:255** | ✅ **唯一全对** |
| 0 | 187×40 | 0:255 | 187:255 | ❌ |
| 1 | 187×40 | 1:255 | 188:255 | ❌ 左 1 右 0 |
| 1.5 | 187×40 | 1:128 | 188:128 | ❌ 半覆盖 |

**规则（从数据里读出来的，不是推的）**：

> 描边**外边缘**落在 `x`，覆盖 `[x, x+1)`。
> 想让最外那一列**满覆盖**，路径必须正好在 0，
> 且描边带的右边缘不越过 `W`
> ⇒ **矩形取 `(W-1) × (H-1)`，一点不平移**。

前两版都错在**平移**：内缩会让边界落在像素中间，
抗锯齿把覆盖分摊到相邻两列，看上去就是"边缘淡了一层 / 断了一截"。

> 这个探针会 segfault（`GraphicsContext` + `MemoryDC` 的退出顺序），
> 但**表格在崩之前已经打完了**，不影响结论。

## `probe_button_edge_columns.py` — 按钮左右边缘是否镜像对称

**判据**：同一深度上左右两侧的颜色应当相同
（左第 `i` 列 ↔ 右第 `W-1-i` 列）。

**实测（现在）**：两种按钮的左右差都是 `[0,0,0,0,0,0,0,0]`，
最外列覆盖率 `1.00 / 1.00`。

**两个判据设计上的坑**（都踩过）：

1. 只比"最外一圈四条边颜色是否相同"——那个判据在
   **整块图形偏移半像素**时也成立。必须**逐列镜像比较**。
2. 右边要从 `x = W-1-i` 取，与左边 `x = i` **同深度**。
   我第一版两边起点不对应，于是"恒定差 1 列"，
   **无论画得对不对都报不对称**。

## `probe_settings_render.py` — 把设置窗口离屏重画成图片

同 `probe_layout_render.py` 的思路（窗口抓图在这个环境不可靠），
额外**自检每种按钮的底色是否真的画出来了**。

### 踩过的两个坑，都在这里

**① `draw_to(parent_colour=...)` 会抹掉整张位图。**

`RoundedButton.draw_to` 在 `parent_colour` 非空时会 `dc.Clear()`，
而 `MemoryDC.Clear()` 抹的是**整张位图**——于是逐个画按钮时，
每画一个就把前面画的全部擦掉，**只有最后一个可见**。

实测三种症状看起来完全不同、成因却是同一个：

| 现象 | 真实原因 |
|---|---|
| "只有最后一个按钮出现" | 前面全被 `Clear()` 抹了 |
| "按钮底色是父窗口的灰" | 该按钮在下一轮被抹了 |
| "中心像素是粉色"(255,206,220) | **取样点落在文字的白色抗锯齿上**，不是按钮没画 |

修法：**不传 `parent_colour`**，改成只铺该按钮自己那一个矩形。

**② 取样点必须避开文字。**

我一开始取"按钮正中心"，读到的是白色文字的边缘混合，
于是误判成"按钮没画出来"，白查了一轮。
取靠左靠上的位置（`rect.x + 12, rect.y + 8`）才是纯底色。

## `probe_version_info.py` — Windows 版本资源怎么调

对照 Roboc 的 `Directory.Build.props`（不是 csproj——那份元数据在一个
`Directory.Build.props` 里），确认 PyInstaller 的
`VSVersionInfo` / `StringStruct` 怎么用。実现在 `tools/version_info.py`。

**关键约束**：`FILEVERSION` 是四个 16 位整数，**不能只有三段**。
`1.2.2` 要补成 `(1, 2, 2, 0)`，少了写不进去。

## `probe_sort_persistence.py` — 排序偏好是不是真的"下次启动也生效"

用户要求："可以选择下次启动时的排序方式。"

所以要验的是**跨启动**，不是"点一下当场变"：开窗口 → 换排序 → 关掉 →
**新建一个** → 断言初始排序与首行都一致。

**数据是特意造的**：`zeta` 访问 5 次、`alpha` 访问 1 次 ——
按频次排序 `zeta` 在前，按路径排序 `alpha` 在前。
**两者首行相同的话这个探针什么都验不出来**，所以频次与字母序必须相反。

实测：默认频次降序 → 点"路径"自动带出该列的升序 → 再点翻成降序 →
设成路径升序后重建窗口，排序与首行都保持。✅

> 它还需要替换 `default_config_path`——否则会往用户真实的
> `%APPDATA%\File Tracker\config.json` 里写排序偏好。
> 那个函数就是为此从"写死在 `__init__` 里的一行"提出来成为函数的。

## `probe_settings_font.py` — 设置窗口的标签会不会被按钮压住

用户截图："题头和按钮挤在一起了" ——「界面语言」「排序方式」「排序方向」
三个标签的**最后两三个字被右边的按钮盖住**。

**跑三种字体条件**（`wx 默认` / `10pt body` / `12pt` 压力测试），
判据是"按钮与标签同行时必须留出间距；另起一行则不必避让"。

### 为什么必须专门测字体

我的探针一开始测**不出来**——它用 wx 默认字体（9pt），量出来标签 85 宽、
按钮从 112 开始，看着完全正常。而真实程序里
`app._apply_body_font()` 有一句**类级**的
``wx.StaticText.SetFont(self, body)``，把之后创建的所有 StaticText
换成 10pt。字体一换，文字的**实际宽度**就与 `GetBestSize()` 缓存的
（创建当时的）宽度对不上了 —— 布局按旧宽度留位、文字按新字体绘制 → 压字。

**教训：凡是"量出来再摆放"的布局，测量与绘制必须用同一套字体与同一个
度量函数。** 缓存尺寸（`GetBestSize()`）在字体被类级改过之后就是错的。

> 另一个坑：把这个类级调用写成
> `wx.StaticText.SetFont(wx.StaticText(), body)` 会直接
> `wxAssertionError: ((HWND)GetHWND())` —— 它要一个**已创建**的窗口，
> 不能用临时控件当参数。

## 性能与置顶那三个（`probe_rebuild_cost.py` / `probe_adjust_reentry.py` / `probe_setwindowstyle_topmost.py`）

| 探针 | 回答什么 |
|---|---|
| `probe_rebuild_cost.py` | 一次「打开」里 `_render_rows` / `adjust_column_widths` **真正做事**几次、原生调用多少次 |
| `probe_adjust_reentry.py` | `adjust_column_widths` 被调 5 次是不是**重入**（打印调用链） |
| `probe_setwindowstyle_topmost.py` | `SetWindowStyle(wx.STAY_ON_TOP)` 到底有没有真的改变 `WS_EX_TOPMOST` |

### 量出来的结论

**① 重建次数与原生调用**

| 指标 | 修前 | 修后 |
|---|---|---|
| `_render_rows`（整表清空重建） | 2 | **1** |
| `adjust_column_widths`（真正做事） | 5 | **1** |
| `GetItemText` 原生调用 | 738 | 69 |

**② `adjust_column_widths` 确实在重入**（探针打出的调用链）：

```
adjust_column_widths
  → SetColumnWidth
    → EVT_SIZE（列表内容宽度变了）
      → _on_list_resized
        → adjust_column_widths      ← 回到自己
```

⚠️ **数"被调用次数"会骗人。** 加了重入护栏之后它**仍会被进入 5 次**，
只是内层立刻返回——探针第一版就是这么骗我的。
**要数"真正做了事的次数"**（判据：这次调用有没有产生 `GetItemText`）。

**③ `SetWindowStyle` 是有效的**，`win32.py` 里那张
"SetWindowStyle 改不动 `WS_EX_TOPMOST`"的表格是**过期文档**：

| 做法 | `WS_EX_TOPMOST` |
|---|---|
| `SetWindowStyle(style \| wx.STAY_ON_TOP)` | **真的变 True** |
| `SetWindowStyle(style & ~wx.STAY_ON_TOP)` | **真的变回 False** |
| `win32.set_window_topmost(True/False)` | 同样有效 |

所以 `app.on_always_on_top` 用 `SetWindowStyle` 是**对的**，
别照着那份旧文档去"修"它。

### ⚠️ 一次**读错需求**的返工（记在这里，因为它是最贵的教训）

用户说"将**导航窗格**内的文字（**包括顶栏标题**）整体缩小 1pt"。

**这句话与代码结构是矛盾的**：导航窗格（左侧）只有地址栏 + 目录树，
**根本没有"顶栏标题"**；有列头标题的是**记录窗格**（右侧）。

我照着字面执行了 —— 把树 10→9pt、地址栏 10→9pt。
用户随后更正：**原意是"记录窗格"**（他熬夜了，说反了）。

> **教训：用户的措辞与代码结构对不上时，先问再改。**
>
> 判据很便宜：**他提到的那个部件，在他说的那个区域里存在吗？**
> 不存在 ⇒ 需求描述有误，问一句就能省掉一轮返工。
> 我当时注意到了"记录窗格才有列头"，但没停下来确认。

**实际落点**：记录窗格（列表条目 + 自绘列头）11pt → **10pt**；
导航窗格那两处**撤回**。现在**全部文字都是 10pt**（按钮/列头/列表/树/地址栏/弹窗），
"2pt 不协调"从根上消失。

### 按**比例**对齐两个窗格（`probe_row_ratio.py`）

用户验收后提最后一条：

> 把记录窗格中的条目行距再增加一点点，**视觉上的间隔比例**就和导航窗格
> 同步了 —— **导航窗格那个比例是最舒服的**。

**"比例"不是"像素"**：两个控件字号不同（列表 11pt、树是系统默认 9pt），
"都加 10px"在视觉上并不一致。要对齐的是 `行高 / 文字高`：

| | 字号 | 行高 | 文字高 | 比例 |
|---|---|---|---|---|
| 记录窗格（改前） | 11pt | 46 | 35 | 1.314 |
| **导航窗格**（基准） | 9pt | 40 | 28 | **1.429** |
| **记录窗格（改后）** | 11pt | **50** | 35 | **1.429** |

（那个 `list_item_extra_height` 字段**后来被删了**：行高现在直接由
`文字高 × row_ratio` 现算，不存在"额外像素"这种字段。）

**这条现在是断言**（`verify_gui.py`）：两边比例差 < 0.02 才算过，
另有阳性对照确认两个比例都 > 1.1（不是"贴着"）。

> **教训：对齐两种控件时，对齐"比例"而不是"像素"。**
> 它们的字号往往不同，同一个像素增量在视觉上并不等价。

## 弹窗字号与导航窗格行高（`probe_dialog_fonts.py`）

**起因**：用户要求"检查设置窗口、所有提示弹窗中的字体、字号（包括标题栏）
是否和『打开』『清空』按钮一致，不一致的统一"；并问"导航窗格的行距可以增加吗"。

### 量出来的：弹窗整整小 1pt

| 控件 | 改前 | 改后 |
|---|---|---|
| 「打开」/「清空」按钮 | **10pt** | 10pt（基准） |
| 设置窗口：自身 + 全部按钮 + 3 个标签 | **9pt** | **10pt** |
| 提示弹窗：自身 + 按钮 | **9pt** | **10pt** |

**根因**：`wx.Dialog` 是**独立顶层窗口**，frame 那边的 `SetFont` 传播过不去，
于是弹窗回落到**系统默认 9pt**。而这段"系统 + 1"的算法当时只写在
`app.set_global_font` 里 —— 弹窗根本拿不到。

修法：把算法收成**唯一的定义**（`widgets.body_font()`），
`ThemedDialog.apply_body_font()` 再把它套到自身与**全部子控件**上
（`self.SetFont()` 只管"默认字体"，**不影响已经建好的子控件**，
所以必须自己走一遍）。

### 量出来的：导航窗格行高**可以**加

`TVM_SETITEMHEIGHT` **实测一一对应**：

| 设定值 | 20 | 24 | 28 | 32 | 40 |
|---|---|---|---|---|---|
| 回读值 | 20 | 24 | 28 | 32 | 40 |

⚠️ **与列表那条不是一回事**：列表的 `LVM_SETITEMSPACING` 在 report 视图下
从 0 设到 40、行高纹丝不动（见「列表行高那一组」）。

⚠️ **它收的是绝对高度，不是"多加多少"** —— 自然高度必须在第一次改之前
量下来存住，否则每进一次主题就长高一点（40 → 50 → 60…）。

### 教训

> **继承来的字体是不可靠的。** 同一个"正文 + 1"的意图，在 frame 的子控件上
> 靠传播成立，在**独立顶层窗口**（对话框）上就不成立。
> **判据只能是逐个控件回读 `GetFont().GetPointSize()`。**

## 列表行高那一组（`probe_row_spacing.py` / `probe_row_height.py`）

**起因**：用户要求"记录窗格条目字号 +1pt、行距适当增加"。
改完之后验证器报了一条失败 —— 而**那条失败暴露了一个长期存在的死代码**。

### 量出来的

**① `LVM_SETITEMSPACING` 在 report 视图下是空操作**

| extra | 0 | 2 | 6 | 10 | 20 | 40 |
|---|---|---|---|---|---|---|
| 回读行高 | 39 | 39 | 39 | 39 | 39 | **39** |

**纹丝不动。** MSDN 也写明该消息只对 icon / small-icon 视图有意义。

⇒ **`METRICS.list_item_extra_height` 从引入起就没生效过。**
当时没有断言量行高，所以没人发现；这次是因为"改了一个假开关"才查出来。

**② report 视图的行高只由字号决定**

| 字号 | 9pt | 10pt | 11pt | 12pt |
|---|---|---|---|---|
| 行高 | 32px | 34px | **39px** | 40px |
| 文字高 | 28px | 30px | 35px | 36px |

⇒ **"加行距"最省事的办法就是加字号**（本次 10→11pt 顺带把行高从 34 抬到 39，+15%）。

**③ 想"字号不动但行更高"，唯一的路是挂一张空图列表**

`wx.ImageList(1, H)` 设为 SMALL 图列表：

| H | 1 | 8 | 16 | 24 | 32 | **40** | **48** |
|---|---|---|---|---|---|---|---|
| 行高 | 39 | 39 | 39 | 39 | 39 | **41** | **49** |

**行高 = max(字号决定的高度, H+1)。**

⚠️ **代价**：report 视图会为第 0 列保留图标位，**路径文字会右移几像素**。
所以这是**换机制**，不是调参 —— 要单独一轮，不要顺手改。

### 教训

> **一个"看起来在调参"的开关，可能从来没接上。**
> 判据只能是**回读几何量**（`GetItemRect(row).height`），
> 不能是"我调了这个值"或"那个 API 返回了成功"。

## 列表规模那一组（`probe_scale_cost.py` / `probe_scale_profile.py`）

审计 M3 说"**无上限、无裁剪、全量渲染**"。前两项（每次打开重建两遍、
列宽量测 O(N)）已修；**"无上限"这一半还没有**——这两个探针就是用来
决定"要不要动、怎么动"的。

### 量出来的（本机，175% DPI）

| 记录数 | 建窗口 | **一次「打开」重建** |
|---|---|---|
| 200 | 597 ms | 124 ms |
| 1000 | 718 ms | 387 ms |
| 3000 | 1171 ms | 994 ms |
| 6000 | 2121 ms | **1906 ms** |

**近线性增长，6000 行时每次双击/回车要等近 2 秒。**

### 时间花在哪（6000 行，一次重建共 2092 ms）

| 分段 | 耗时 | 调用次数 |
|---|---|---|
| **`InsertItem`** | **1533 ms** | **6000** |
| `SetItem` | 104 ms | 18000 |
| `SetItemBackgroundColour` | 80 ms | 6000 |
| 量列宽 | 61 ms | 2 |
| `SetItemTextColour` | 26 ms | 6000 |
| 读库 `load_unpinned` | 13 ms | 1 |

⚠️ 分段会**重叠**（`_render_rows` 里包含 `InsertItem`），不要相加——
看的是"哪一项最贵"。

### 结论

瓶颈是 **`wx.ListCtrl` 的逐行 `InsertItem`**（约 0.26 ms/行），
不是读库、不是量列宽、也不是排序。所以：

* **"裁剪记录"治不了根**：5000 行仍要 1.3 秒。
* 真正的解法是**虚拟列表**（`wx.LC_VIRTUAL` + `OnGetItemText`），
  只渲染可见行。
* **但那是一次有风险的改造**：虚拟列表**不支持**逐项
  `SetItemBackgroundColour` / `SetItemTextColour`——而整行高亮、
  预选跟随、顶置黄底全都依赖它们。`_render_rows` / `_apply_selection_highlight`
  / `_paint_column_separators` 都要跟着改，属于"改完必须全面重验"的那一类。

所以这一半**留作决策项**，不在这轮顺手做。

## 体积审计那一组（一轮审计留下的，六个）

这一组是为"16.12 MB 里都是什么、能省多少"写的。**都没有弹窗**
（它们只读产物，不建窗口），留着的价值是"下次想省体积时不用从零查"。

| 探针 | 回答什么 |
|---|---|
| `probe_bundle_size.py` | 产物归档里每一项多大；按 wx / 可疑 / images 分类 |
| `probe_pyz_contents.py` | PYZ 里 130 个模块是哪些；与"应用真正 import 的"做差集 |
| `probe_used_modules.py` | 导入应用（并建出真实窗口）后，`sys.modules` 里到底加载了什么 |
| `probe_size_candidates.py` | 哪些资源**零引用**（AST 扫字符串字面量）；谁拉进了加密/网络模块 |
| `probe_libcrypto_source.py` | `libcrypto-3-x64.dll`（2.11 MB）的依赖链：它 ← `_hashlib` ← `hashlib` ← `tarfile`/`zipfile` |
| `probe_standardpaths_hang.py` | `wx.StandardPaths.Get()` 在没有 `wx.App` 时的行为（见上面护栏那节） |

### 结论（已实测，别重复踩）

* **两张 `FileTracker_v1.*-Overview.jpg` 共 358 KB，全代码库零引用** ——
  `datas` 打的是整个 `images/` 目录，所以被原样带进去了。纯赚。
* **`ast` / `dis` 不能排**：`inspect` 依赖它们，排掉会让
  `pyi_rth_inspect` 在启动时抛 `ModuleNotFoundError`（实测，会弹崩溃框）。
* **`socket` 不能排**：进程活着但**窗口起不来**。
* 排 `tarfile, hashlib, ssl, select, selectors, email, http, urllib, xml, bz2`
  这一组：产物 **13.51 MB**（−16%）、`libcrypto` 消失、`--selftest` 正常 ——
  但这个组合**只验过 selftest，没跑过完整 GUI 回归**，采用前必须补。

## ⚠️ 探针必须自己关掉 wx 的模态框（`_probe_guard.py`）

用户反馈过一次：

> 我帮你点掉了这些窗口，对测试结论有没有影响？以后你可以自动关闭吗？
> 我生怕你思考卡住又多等几十分钟。

那一轮一共弹了三类框，**没有一个是我有意弹的**：

| 框 | 谁弹的 | 怎么根治 |
|---|---|---|
| `wxWidgets Debug Alert`（断言失败） | **wx**：断言不抛异常，而是弹模态框等人点 | `wx.DisableAsserts()` |
| `Unhandled exception in script` | **PyInstaller** 运行时钩子 | 别造出坏产物 + 先杀进程 |
| 探针自己的窗口没关 | 探针 | `finally` 里 `Destroy()` |

**第一类是真正危险的那个**：断言框会**一直等**，而探针是无人值守的
——进程就停在那里，还会连累整场会话。

### 规矩

写探针时：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _probe_guard import harden_wx, install_excepthook

install_excepthook()   # 崩溃时打清楚 + 非零退出，而不是弹框
harden_wx()            # **关掉断言框**（关键）
import wx              # 之后再 import wx

app = wx.App()
```

跑别人的探针（硬限时，超时就杀）：

```python
from _probe_guard import run_probe
code, out = run_probe("probe_xxx.py", timeout=120)
```

### 为什么"禁用断言"不削弱结论

`wx.StandardPaths.Get()` 那次的例子：断言框开着 → 挂住；
关掉 → 顺利返回。

看起来结论变了，其实**更清楚了**：

* 关掉断言 == 假装有人点了「继续」，于是看到"这句本身不抛异常"
  ⇒ 证明 `except (OSError, ValueError)` **接不住**它。
* 而失败的**不是这次调用，是 wx 的断言处理**：
  断言失败 → 弹框 → 无人点 → 停住。
  也就是说，**产物挂起的原因就是那个没人点的框**。

结论一样可靠，区别只是不再打扰人。**判据从"会不会卡住"变成
"有没有抛异常 / 能不能返回"**——后者还能重复自动跑。

## `probe_open_focus.py` — 「打开」跟不跟最后一次选中

用户为这个 bug 报过**两次**：

1. "记录窗格中无论选中哪条记录，「打开」按钮都只会响应左侧导航窗格的选中项。"
2. "打开按钮还是不能正确执行记录窗格内最后一次选中条目，
   依然优先响应上次使用的导航窗格条目。"

第一次我以为绑 `EVT_LIST_ITEM_SELECTED` 就够了。第二次才发现真正的原因在
**事件来源**上，不在时序上：

> `EVT_TREE_SEL_CHANGED` **分不清"用户点的"和"代码改的"**。
> 而 `reveal_in_tree` 会调 `tree.SelectItem()`（地址栏回车、启动定位上次目录）。
> 于是用户的列表选择被这个程序化事件悄悄改成 "tree"。

修法：只绑**程序不可能产生**的事件 —— `EVT_SET_FOCUS` 与
`EVT_TREE_KEY_DOWN`。`SelectItem()` 一个都触发不了。

### 这个探针教我的两件事

* **合成鼠标事件（`wx.UIActionSimulator`）不可靠。** 单独跑能触发，
  跑在整串检查中间时一个事件都收不到（窗口位置、焦点、遮挡都会影响）。
  我为此白跑了四五轮，最后换成直接 `ProcessEvent` 派发到真实处理器上——
  确定性的，且验的是同一环逻辑。
* **`wx.DisplaySize()` 返回元组，不是 `wx.Size`。** 写成 `display.width`
  直接 `AttributeError`。

## `probe_item_colour.py` — `wx.ListCtrl` 的文字颜色能不能**按列**设

会开窗口。连续对一个 item 设两次不同颜色，看读回来是哪一个。

**结论：`wx.ListCtrl` 的文字颜色是"按行"的，没有按列的版本。**

| 检查 | 结果 |
|---|---|
| 连续两次 `SetItemTextColour(1, ...)` | 只有**最后一次**生效 |
| `wx.ItemAttr.SetTextColour(colour)` | **没有列参数** |
| 虚拟列表 `OnGetItemAttr(item)` | 只有 item，**没有 column** |
| `wx.ListCtrl` 里含 `Column`+`Attr` 的方法 | **不存在** |

**所以做不到"路径列纯黑、其余列灰"。** 用户要求
"把所有路径记录条目文字颜色恢复为纯黑/纯白"，
整行统一色恰好就是他要的，也顺带修掉一个真 bug：
原来先设路径列、再循环设频次/日期/时间列，**后者把前者覆盖了**——
整行其实都是灰的，正是用户抱怨的那个"灰"。

## `probe_nav_variants.py` — 导航窗格那圈白框的**真正**根因

会开窗口（每个变体一个独立 Frame）。量
`GetWindowRect` 与 `GetClientRect` 的差值 = **非客户区边框宽度**。

**这是本项目最值得看的一次排查**，因为我连错两次：

| 我的判断 | 实际结果 |
|---|---|
| ① 内层树的 `WS_EX_CLIENTEDGE` | 去掉后用户反馈"**白框还在**" |
| ② `wx.DIRCTRL_3D_INTERNAL` 样式 | 实测**与它无关** |
| ③ **`GenericDirCtrl` 默认带 2px 非客户区边框** | ✅ **是真的** |

实测四个变体：

| 样式 | 非客户区（每边） |
|---|---|
| `DIRCTRL_MULTIPLE` | 2 px ← **默认就有** |
| `DIRCTRL_MULTIPLE \| DIRCTRL_3D_INTERNAL` | 2 px ← 与 3D 无关 |
| **`DIRCTRL_MULTIPLE \| wx.BORDER_NONE`** | **0 px** ✅ |
| `DIRCTRL_MULTIPLE \| wx.BORDER_SIMPLE` | 1 px |

### 三条通用教训

1. **窗口绘制分"客户区"和"非客户区"。**
   `SetBackgroundColour` **只管客户区**；边框/标题栏/滚动条属于非客户区，
   由**系统主题**绘制，设色一律无效——**只能改样式位**
   （`wx.BORDER_*` / `WS_BORDER` / `WS_EX_*`）。
2. **判据要用几何量**：`窗口矩形宽 − 客户区宽`。
3. **这个环境下"像素取样"不可靠。** 我为此白跑了好几轮：
   `WM_PRINTCLIENT` / `PrintWindow` / `GetDC+BitBlt` 全返回黑或白，
   `GetPixel` 也读到过明显不对的值
   （一个明确设了 `#242424` 的普通 `wx.Panel` 被读成 `#FFFFFF`）。
   **能用几何量或属性判定的，就不要去读像素。**

### 还有一个坑：对比实验时控件会重叠

早期几版把新控件直接建在旧控件上面 —— 两个窗口叠着，
取样取到的是**旧的那个**，于是"无论怎么改结果都一样"，
白白得出"改了没用"的错误结论。
**做对比实验时，务必先 `Destroy()` 掉旧的（不是 `Hide()`），或者各用一个 Frame。**

## `probe_sash_border.py` / `probe_sash_geometry.py` / `probe_sash_drag.py` — 两栏之间的分界线

会开窗口。

| 做法 | 几何结果 |
|---|---|
| 默认 sash 可见 | 左窗右边界 300、右窗左边界 304 → **间隙 4**，画成 `#F0F0F0` |
| `SetSashInvisible(True)` | 两个边界都是 300 → **间隙 0**，白线消失 |

sash 由 wx 的 `wxSashWindow` 那套 3D 绘制负责，取系统色
`SYS_COLOUR_BTNFACE`（本机 **`#F0F0F0`**），`SetBackgroundColour` 对它无效。

**顺带发现：分割条的事件不可靠**

```
调 SetSashPosition(520) 后的事件 = []          ← 两个事件都没来
改窗口大小后的事件             = [('FRAME_SIZE', 520)]
```

`EVT_SPLITTER_SASH_POS_CHANGED` / `..._CHANGING` 在**代码调用**
`SetSashPosition` 时不触发。自绘的线因此留在旧位置（sash 520、线在 399）。
→ 摆线的动作要在 `on_window_resize` 里也做一次。

## `probe_tree_scrollbar.py` — 树的滚动条

会开窗口。用 `GetScrollBarInfo` 问滚动条的实际矩形与状态。

**结论**：树的 `WS_VSCROLL` / `WS_HSCROLL` **都是 False**，
两个滚动条 `GetScrollBarInfo` 都报"不可见"。
所以导航窗格那圈白框**不是滚动条**——这条排除掉了。

## `probe_tree_frame.py` — 深色下导航窗格的容器底色

会开窗口。把 `GenericDirCtrl` 的**子窗口层次**与各层底色全打印出来。

**结论**：`GenericDirCtrl` **自己**的底色曾是 `(240,240,240)`（浅灰），
而当时只设了内层 `SysTreeView32`。容器也要设。

> 一般教训：wx 的复合控件（`GenericDirCtrl`…）常常"外层是容器、
> 里层才是真控件"，只设里层会留下一圈没改到的底色。

## `probe_tree_labels.py` — 目录树里驱动器节点叫什么

会开窗口。打印根节点的前两层标签与 `GetPath` 结果。

**结论**：驱动器节点的显示名是 `SYSTEM (C:)` / `ACTIVE (D:)`，**不是** `C:`。
不做这一步，"地址栏导航"在任何盘符路径上都会在第一级匹配失败。

## `probe_lazy_expand.py` — 树是不是懒加载的

会开窗口。对比 `Expand` 前后一个节点的子项数量，并测量逐级展开的耗时。

**结论**：`wx.GenericDirCtrl` 的树是**懒加载**的——未展开时 `GetFirstChild`
返回空；`Expand` 之后立刻就有数据（同步生效，不必 `Yield` 或等待）。
所以"先展开、再取子项"的顺序不能反。

## `probe_multiselect.py` — 多选树上 SelectItem 的语义

会开窗口。在多选与单选两棵树上各选一个节点，再连续换选几个。

**结论**：带 `wx.DIRCTRL_MULTIPLE` 的树是**多选**的，`SelectItem` 是**追加**
而不是替换——不清空的话会留下两项同时高亮。另外这个控件上
`GetSelection()` 会直接抛 `wxAssertionError`，必须用 `GetSelections()`。

## `probe_native_lvm.py` — 原生列格式消息在这台机器上可用吗

会开窗口（一个裸的原生窗口，不涉及 wx 控件）。用 `CreateWindowExW` 直接建一个
`SysListView32`，对 `LVM_SETCOLUMN` / `LVM_GETCOLUMN` 做逐字段探测。

**结论**：**连完全不涉及 wx 的裸原生控件，`LVM_SETCOLUMN` 也返回 0（失败）。**
所以"频次列居中"走不通原生消息，这不是 wx 的包装问题。
这正是改用 `wx.dataview.DataViewListCtrl` 的直接依据。

## `probe_render_noise.py` — 能不能用像素当判据

会开窗口。先做**同格式连拍两次**的对照量出噪声，再比较 `fmt=LEFT` 与
`fmt=CENTER` 的差异。

**结论**：同格式连拍两次就有 **21672** 个像素不同，而 LEFT vs CENTER 是 21671——
**信噪比不足以支撑任何判断**。（第一版更糟：窗口没置前，把别的程序截了进来。）
这条探针的价值是**否定**一种方法：别再试图用截图证明这件事。

## `probe_dpi_units.py` — wx 报告的坐标是什么单位

会开窗口。打印 `Display.GetClientArea()`、窗口的 `GetSize`/`GetClientSize`、
`FromDIP`、`GetDPI` 等。

**结论**：本机是 2560×1600 @ **175%** 缩放，`GetClientArea()` 返回的是
**物理像素** 2560×1516，而 `SetSize` 收的也是物理像素。
所以"窗口按工作区夹取"的比较是同一单位下的比较，成立。

## `probe_dataview_api.py` — DataViewListCtrl 够不够用

会开窗口。逐项确认改用 `DataViewListCtrl` 之后原有行为能否保住。

**结论**：够用。列对齐 (`AppendTextColumn(..., align=...)` 且
`GetColumn().GetAlignment()` 可**回读**)、按行底色（靠重写 `OnGetItemAttr`，
因为它没有 `SetRowBackground`）、取值、选中、动态列宽、整表重建、
双击/右键/列头事件类型——全部覆盖。

## 第二轮反馈：深色主题为什么没生效 / 按钮为什么偏大

（当时的探针已合并，结论留在这里。）

**结论一（深色主题）**：本机注册表 `AppsUseLightTheme = 1`，
即**系统就是浅色**，所以程序显示浅色是正确行为，不是没适配。
真正的问题在**原生控件**上：列表表头、滚动条、菜单、`MessageBox`
由系统绘制，`SetBackgroundColour` 对它们无效。

> **这条当时写成了"Win32 通用控件的限制"——那个判断后来被推翻了。**
> 真正的解法是进程级的 `uxtheme.SetPreferredAppMode`，
> 见下面 `probe_darkmode_api.py`。**写"做不到"之前先确认自己找过几种办法。**

**结论二（按钮偏大）**：`wx.Window.FromDIP` 在控件**尚未完成父级绑定**时
退回 96。同一个按钮：

| 运行方式 | `FromDIP(24)` | 实际按钮高 |
|---|---|---|
| 直接 `python src/main.py` | 24 | 24 逻辑像素 |
| 先 `SetProcessDpiAwareness(2)` 再跑 | 168 → 42 | 42 物理像素 |

所以尺寸不能用 `FromDIP` 算，要主动问父窗口的 DPI——
见 `widgets.dpi_of`（它必须 import wx，所以放在 widgets 而不是 theme）。

---

## 试过但**不通**的路（留在这里免得再走一遍）

### 用 `ScreenDC.Blit` 抓窗口截图

抓的是**屏幕像素**：窗口被别的窗口盖住时，抓到的是别人的画面。
两次尝试都因此得到错误结论。

### 用 `PrintWindow` 抓窗口自身

`PW_RENDERFULLCONTENT (0x2)` 在 DWM 合成的窗口上**返回纵横交错的乱码**；
`flags=0` 同样不可靠。

### 从窗口自己的 DC 做 `BitBlt`

不依赖窗口置前，但抓到的仍是乱码。

**结论：这个项目没有可靠的像素抓取手段。**
"观感"这一半只能由人眼判断；能自动化的只有数值与可回读的属性
（列对齐、尺寸、对比度、行属性、原生样式位）。**把这两半分清楚**，
比继续折腾抓图有价值。

### 在单元格里用换行符分两行显示

`DataViewListCtrl` 会**吞掉** `\n`——`GetTextValue` 读得回来，
但行高不变（实测仍是 23 像素）。所以"日期与时间分两行"做不到，
最终改成**两个独立列**。

---

## 双重顶栏与"看不见 ≠ 不存在"

**先看这条，它是一个推理错误的记录。**

我一度报告"原生表头已隐藏"，依据是"深色主题下只数到一条顶栏"。
用户一句话点破：**"深色主题双重顶栏不可见，是因为此前你修不好的反色 bug。"**

深色下"只有一条"从来不是"没有重复"的证据——那条重复的顶栏
因为白字浅底而**看不见**。**我把渲染 bug 当成了功能正确。**

> 判据必须是**几何量**（占不占位置），不是"可不可见"。

### 原生表头的事实（都在 `probe_header_*` 系列里量过）

| 做法 | 第一行 y | 结论 |
|---|---|---|
| `LC_REPORT` | **36** | 表头占着位置 |
| `LC_REPORT \| LVS_NOCOLUMNHEADER`(0x4000) | **36** | **被 wx 丢掉了**，无效 |
| `LC_REPORT \| wx.LC_NO_HEADER`(0x800) | **0** | 表头不占位置 ✅ |

两个坑：

1. **原生 `LVS_NOCOLUMNHEADER` 传进 `wx.ListCtrl` 会被丢掉**——
   原生 `GWL_STYLE` 里那一位没置起来。wx 用自己的 `LC_NO_HEADER`(0x800)。
2. **表头窗口一直存在**（`SysHeader32` 会被创建），所以
   "在不在""可不可见"都不是判据，**第一行的 y 坐标**才是。

### 为什么最后仍是自绘表头

用户反馈："深色主题下'访问的路径'等一栏**文字已经正确反色但背景还是浅色**，
导致看不见。" 两条系统路都不通：

==========================  ================================================
做法                         结果
==========================  ================================================
``SetHeaderAttr()``          返回 True，但原生表头仍是 ``#F0F0F0``
``SetWindowTheme``           返回 True，表头像素仍是 ``(255,255,255)``
``NM_CUSTOMDRAW`` 子类化      **能成，但没采用**——见下
==========================  ================================================

第三条是 ``SetWindowLongPtrW(GWLP_WNDPROC)`` 级别的窗口过程替换，
**写错会直接崩掉进程**。本项目已经因为"改动过大"回归过两次，
不值得为一个表头冒这个风险。最终用**纯 wx 的自绘表头**
（``file_tracker/header.py``），并把原生表头**从布局上挤掉**
（``wx.LC_NO_HEADER``）。

代价是要自己同步列宽与点击——由 ``app._sync_header`` 负责，
**每次 ``adjust_column_widths`` 之后都必须调一次**。

---

# 第三轮反馈相关的探针

## `probe_topmost.py` — `SetWindowStyle` 有没有真的置顶窗口

会开窗口。量四种做法的 `WS_EX_TOPMOST` 扩展样式位。

**结论**：`wx.Frame.SetWindowStyle(style | wx.STAY_ON_TOP)` **不会改变
`WS_EX_TOPMOST`**，但 `GetWindowStyle()` 会返回 `True`——
**它会骗你**。补 `Hide()+Show()` 也没用。只有
`SetWindowPos(HWND_TOPMOST / HWND_NOTOPMOST)` 真的生效。

这就是用户报的"顶置功能本身都失效了"的根因：
代码看起来完全正确，状态查询也返回 True，窗口就是不理你。

## `probe_header_event.py` — 列头点击能不能拿到列号

会开窗口，在**四种不同的点击位置**上真实点击表头。

**结论**：`dv.EVT_DATAVIEW_COLUMN_HEADER_CLICK` 在 `DataViewListCtrl` 上
**一个事件都收不到**；而且 wxPython 4.2 没有公开 `wx.DataViewEvent`，
事件对象上也没有 `GetColumn()`。

> **但当时的处置是错的**：我因此**把列头点击排序这个原版功能删掉了**，
> 用户实测指出"所有点击功能全部失效"，评价"你在越修越烂"。
> 正确做法是**换回 `wx.ListCtrl`**（它的 `EVT_LIST_COL_CLICK` 一直是好的），
> 而不是拿一个功能换另一个功能。
> **教训：遇到"当前控件做不到"时，先问"换掉会失去什么"。**

## 深色表头：两条系统路都不通（结论已并入 `header.py`）

（当时的探针已合并，结论留在这里。）

表头是一个真实的原生 `SysHeader32`。两条系统路都试过，**都不生效**：

* `SetHeaderAttr()`——返回 True，但表头仍是 `#F0F0F0`
* `uxtheme.SetWindowTheme(hwnd, "DarkMode_Explorer")`——返回 True，
  表头像素仍是 `(255,255,255)`

第三条路 `NM_CUSTOMDRAW` 子类化**能成但没采用**（窗口过程替换，
写错会崩进程）。最终用**纯 wx 自绘表头**，见 `header.py`。

**滚动条、右键菜单、`MessageBox`** 由系统绘制——
它们的解法是进程级的 `uxtheme.SetPreferredAppMode`，
见 `probe_darkmode_api.py`。**不是"没有受支持的接口"。**

## `probe_lvm_final.py` — LVM_SETCOLUMN 到底能不能用（**结论：不能**）

会开窗口。试六种结构体组合（仅 FMT / 带 cx / 带 iSubItem / 带空串 / 带文字 / 全都要）。

**结论**：``LVM_SETCOLUMN`` **一律返回 0**，``LVM_GETCOLUMN`` 回读的也一直是垃圾值。
配合 `probe_native_lvm.py`（裸原生控件上同样失败），可以确定
**这条接口在本环境不可用**。

**所以"频次列居中"不能走原生消息。** 而 `wx.ListCtrl` 的列头点击
（`wx.EVT_LIST_COL_CLICK`）是原版就有的功能、必须保留——
两相权衡，居中改成补前导空格，**控件仍用 `wx.ListCtrl`**。
中间一版为此换成 `DataViewListCtrl`，结果弄丢了列头点击，
用户评价"你在越修越烂"——**这笔账记在这里，别再换控件。**

## `probe_darkmode_api.py` — 深色主题的关键调用在这里

会开窗口。检查 `uxtheme.dll` 有没有 `SetPreferredAppMode`。

**结论**：**按函数名取不到，按序号 135 可以取到**，调用返回成功。

这是深色主题里最关键的一步：调用 `SetPreferredAppMode(2)`（ForceDark）之后，
**滚动条、列表表头、菜单、MessageBox 这些由系统绘制的控件都会变深**。
必须在**创建窗口之前**调用。

前几轮我一直在"逐个控件设色"，所以总有一些变不了，还错误地把它写成了
"已知代价"。**那不是已知代价，是没找到接口。**

## `probe_header_event.py` — DataView 的列头点击收不到（历史记录）

会开窗口，在四种不同点击位置真实点击 `DataViewListCtrl` 的表头。

**结论**：一个事件都收不到；wxPython 4.2 也没公开 `wx.DataViewEvent`，
事件对象上没有 `GetColumn()`。**这是"不要用 DataViewListCtrl 换掉
wx.ListCtrl"的直接证据。**

## `probe_pathbar_focus.py` — 地址栏"没有交互"是视觉问题

会开窗口，检查输入框的焦点、可见性、自绘面板有没有盖住子控件。

**结论**：焦点一直是好的（点击后 `HasFocus = True`）。
**问题是纯视觉的**——输入框底色与面板底色几乎一样，看起来像静态标签。
修法是让它有区别于面板的底色 + 焦点时用强调色描边。

## 置顶底色：一个改了五轮、方向一直错的例子

（当时的探针已合并，结论留在这里——**这条最值得看**。）

我认定"置顶行看着没生效"是**颜色选得不好**，于是量了对比度
（`#FFF8DC` 与白底只有 **1.065**），换成更饱和的黄、又换成跟随强调色的浅蓝。

用户明确否决两次，最后点明：

> **"不是你调色的问题，是此前不知道动错了哪些代码导致它失效。"**

真正失效的是**行属性根本没被应用**（换成 `DataViewListCtrl` 之后
底色的施加方式变了）。**我在错误的层面上改了五轮。**

后来又截图对比："你现在的黄色饱和度太低，适当提高。"
最后用户自己调好并指定：**`#ffffb7`**。

> **两条规矩**：
> ① 用户说某个视觉元素不对时，**先确认它有没有被画出来**，再谈好不好看；
> ② **颜色由用户定，不要拿对比度计算去推翻它。**

**按钮尺寸**：`wx.Window.FromDIP` 在控件**尚未完成父级绑定**时退回 96。
同一个按钮：

| 运行方式 | `FromDIP(24)` | 实际按钮高 |
|---|---|---|
| 直接 `python src/main.py` | 24 | 24 逻辑像素 |
| 先 `SetProcessDpiAwareness(2)` 再跑 | 168 → 42 | 42 物理像素 |

所以尺寸不能用 `FromDIP` 算，要主动问父窗口的 DPI——
见 `widgets.dpi_of`（它必须 import wx，所以放在 widgets 而不是 theme）。

