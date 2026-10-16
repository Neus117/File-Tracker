<div align="center">

# ⭐ File Tracker

**自动记录你访问过的文件夹 —— 按使用频率和时间排序，双击即跳转。**

[**简体中文**](README.md) ｜ [English](README.en.md)

![浅色主题](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-light.jpg)

![深色主题](https://raw.githubusercontent.com/Neus117/File-Tracker/main/images/FileTracker_v1.2.4-dark.jpg)

[**下载最新版**](https://github.com/Neus117/File-Tracker/releases/latest) ·
[全部版本](https://github.com/Neus117/File-Tracker/releases) ·
[已知限制](#已知限制)

</div>

---

## 功能

### 左侧 · 文件选择器

- 树状浏览导航
- **地址栏**：粘贴或输入路径后回车，直接跳到该位置**并记录一次访问**（`Ctrl+L` 聚焦）
- 文件夹与文件都能选；选中文件时双击打开它所在的文件夹
- 记住上次浏览的位置，自动重置横向滚动条

### 右侧 · 路径记录器

- 自动记录访问过的路径
- **点列头排序，并记住你的选择** —— 下次启动就用它
- **设置窗口**（底部右侧的齿轮按钮）：切换界面语言、选择排序方式
- 中英双语：跟随 Windows 显示语言，也可手动指定，切换即时生效
- 顶置 / 取消顶置 —— **新顶置的排在最前**
- `Ctrl+C` 复制路径 · 右键菜单 · 单条删除或全部清空
- 浅色 / 深色主题跟随系统

---

## 使用说明

| | |
|---|---|
| **下载** | 到 [Releases](https://github.com/Neus117/File-Tracker/releases/latest) 下载 `File.Tracker_v1.2.5.exe`，双击即用，无需安装 |
| **数据库** | 首次运行会在 `C:\Users\<你的用户名>\` 下创建 `file_tracker.db`（v1.0 时代叫 `file_access.db`） |
| **开机自启** | `Win+R` 输入 `shell:startup` 回车，把程序的快捷方式放进打开的文件夹 |
| **卸载** | 删掉 exe 和 `file_tracker.db` 即可 |
| **查看版本** | `File.Tracker_v1.2.5.exe --version` → 打印形如 `File Tracker 1.2.5+ae4a6f4`，`+` 后面是构建它的提交 |

> **关于资产名**：从 v1.2.0 起统一为 `File.Tracker_v<完整版本号>.exe`。
> 此前四个版本各不相同（`File.Tracker_v1.02.exe` 还少一个点），容易下错。
>
> **没有控制台时**（例如双击运行），`--version` 会改为写一份到
> `%APPDATA%\File Tracker\version.txt`，并弹一个 6 秒后自动关闭的提示框。

---

## 与 v1.1.0 相比

v1.1.0 发布于 2024-10-14，v1.2.5 发布于 2026-10-16。**功能变多了，体积反而小了。**

| | v1.1.0 | **v1.2.5** |
|---|---|---|
| 体积 | 15.76 MB | **13.31 MB** |
| 界面语言 | 仅中文 | **中英双语，可切换** |
| 排序 | 固定按频次 | **可选排序列与方向，跨重启记住** |
| 顶置顺序 | 新顶置的排最后，重启后位置会变 | **新顶置的排最前，跨重启保持** |
| 设置窗口 | 无 | **有**（语言 + 排序） |
| 深色主题 | 部分控件不跟随 | **自绘控件全程跟随** |
| 地址栏回车 | 不打开资源管理器 | **真的打开** |
| 自动化测试 | **0 条**（且测试文件 import 的名字两个都不存在） | **192 条单元测试 + 158 项界面检查** |
| 构建流程 | **没有**（无 `.spec`、无脚本、无 CI） | `build.ps1` + 9 道门禁 + GitHub Actions |
| 产物自报版本 | 不能 | **能**（名字 / 版本 / 提交） |
| 属性页版本信息 | 几乎空白 | **五项齐全** |

**体积是怎么降下来的**（在功能变多的前提下）：

- 只打包运行时真正读取的资源 —— 此前整个 `images/` 目录都被塞进去，包括本页的展示图
- 排除只有标准库内部才用到的 `tarfile` / `hashlib` / `email`，
  它们会连带把 2.11 MB 的 `libcrypto-3-x64.dll` 拉进产物

---

## 已知限制

**记录条数很多时，「打开」一条记录会变慢。** 本机实测（175% DPI）：

| 记录数 | 一次「打开」之后的完整刷新 |
|---|---|
| 200 | 约 0.12 秒 |
| 1000 | 约 0.39 秒 |
| 3000 | 约 0.99 秒 |
| 6000 | 约 1.9 秒 |

瓶颈是 `wx.ListCtrl` 逐行插入（6000 行里它占 1.53 秒）—— **不是**读数据库
（13 ms），也**不是**算列宽（61 ms）。所以**限制记录条数治不了根**。

真正的解法是改用虚拟列表，但那会动到整行高亮、悬停跟随、顶置底色三处显示逻辑，
需要单独一轮改造。

**日常使用（几十到几百条）完全感受不到。** 测量脚本与完整结论见仓库
`tools/probes/README.md` 的「列表规模那一组」。

---

## 依赖

- Python 3.11
- 1.1+ 版本依赖 wxPython；打包需要 PyInstaller
- 完整清单见 `requirements_v1.1+.txt`，环境文件是 `environment_v1.1+.yml`

> **Python 版本不能随便升。** `wxPython==4.2.2` 在 PyPI 上最高只提供到 **cp313**
> 的 wheel（实测 cp38–cp313），而本机 conda base 是 3.14 —— **装不上**。
> 必须用 `environment_v1.1+.yml` 建 3.11 环境。

---

## 开发者

### 安装

```bash
git clone https://github.com/Neus117/File-Tracker.git
cd File-Tracker
conda env create -f environment_v1.1+.yml
conda activate ft_env
pip install -r requirements-dev.txt
```

两个环境文件里的环境名都是 `ft_env`，**不能同时装**。换版本前先
`conda env remove -n ft_env`。

### 调试

```bash
python src/main.py               # 启动应用
python src/main.py --version     # 打印版本（含构建它的提交）
python src/main.py --selftest    # 不创建窗口的自检
pytest                           # 跑测试
```

排查目录树时有一个探针可以打印真实的控件结构：

```bash
python tools/probes/probe_tree_labels.py
```

### 代码结构

```
src/
├── main.py                     入口：python src/main.py
└── file_tracker/
    ├── core.py        ─┐
    ├── store.py        │  不依赖 wx —— 可以在没有桌面会话的环境里测试
    ├── config.py       │
    ├── tree_nav.py     │
    ├── theme.py        │
    ├── win32.py       ─┘
    ├── lang.py           双语（L("中文","English") 写在调用点）
    ├── widgets.py        自绘控件
    ├── header.py         自绘列头
    └── app.py            主窗口
```

**分层是为了让判断可以自动验证。** 窗口尺寸计算、路径规范化、目录树路径匹配
这些以前埋在窗口类里、只能靠人眼看的逻辑，现在都在不依赖 wx 的模块里，
由 `tests/` 覆盖 —— `tests/test_core.py` 里有一条测试专门守着这条边界。

> 旧的 `src/File Tracker_v1.1.py` 兼容垫片已在 v1.2.4 删除。它的文件名**带空格，
> 根本不可能被 `import`** —— 这也正是当初换掉它的原因。

### 构建与验证

```powershell
# 构建：环境检查 → 测试 → 打包 → 产物自检 → 报告哈希
powershell -File build.ps1

# 在真实桌面会话里核对界面（会开一个窗口，约 3-5 秒后自动关闭）
powershell -File tools/verify_gui.ps1
```

**九个静态/动态门禁**（全部在 `build.ps1` 与 CI 里）：

| 检查器 | 查什么 |
|---|---|
| `pytest` | 192 条单元测试，不依赖 GUI |
| `check_wiring.py` | 「定义了却从来没有人读取」的东西 |
| `check_dialogs.py` | 给了两个按钮却没读返回值（曾报过"两个按钮功能完全一致"） |
| `check_duplicate_methods.py` | 同名方法定义两次 —— Python 只用后一个，**改前一个没有任何效果** |
| `check_audit_items.py` | 审计条目逐项清账（50 条判据） |
| `add_bom.py --check` | `.ps1` 的 UTF-8 BOM —— 编辑工具会剥掉它，而 PowerShell 5.1 会因此把中文读成乱码 |

**其中三个带阳性对照**（`*_negative.py`）：先造一个必然被拦的样本，
确认工具真的会报错。**「返回通过」和「根本没有运行」在输出里长得一模一样**，
所以阴性的结果必须先证明检测器跑了。

`build.ps1` 最后会真的运行产物的 `--version`，确认它**自报的提交哈希**与本次
构建一致 —— 「我以为我写进去了」和「它真的在里面」是两件事。它还会回读产物的
**版本资源**，确认属性页里那五项真的写进去了。

发版流程见 `docs/RELEASING.md`。

---

## 贡献

欢迎提交 issue 或 pull request。
