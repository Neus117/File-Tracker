# 发版流程

**本文件是 File Tracker 发版的唯一依据。** 每一条都是踩出来的，不是流程洁癖。

---

## 一、什么时候可以发

- `pwsh -File build.ps1` 全绿（含产物 `--version` 自报哈希核对）
- `pwsh -File tools/verify_gui.ps1` 全绿（会开一个窗口，约 3-5 秒）
- 工作区干净——**产物自报的哈希必须对应一个真实提交**

---

## 二、三条版本纪律

### 纪律一：先提交版本号，再重建，再打标签

否则产物内嵌的提交哈希与标签指向的提交不一致，`--version` 会说谎。

```powershell
# 1. 改 src\file_tracker\core.py 里的 APP_VERSION
# 2. 单独提交这一个改动
git add -A
git commit -m "Release: 版本 1.2.0"
# 3. 重建 —— 让产物内嵌的哈希对上这个提交
pwsh -File build.ps1
# 4. 打标签（注释即 release 描述）
git tag -a v1.2.0 -F notes.txt
# 5. 推送
git push origin main
git push origin v1.2.0
```

### 纪律二：产物必须能自报"是哪个提交构建的"

`build.ps1` 最后一步会真的去跑产物的 `--version`，确认它自报的哈希与本次
构建一致。**"我以为我写进去了"和"它真的在里面"是两件事。**

这一条不是形式主义：`v1.1.0` 那个标签指向 `6c197c2`（一条 README 提交），
而真正的代码提交是 `7fd8f20`。用户报障时，从版本号判断不出他装的是哪一个。

### 纪律三：已发布的标签绝不能移动，要改就发新版本号

移动一个**已发布**的标签，会让同一个版本号对应两个内容不同的 exe，
而自报的哈希也随之改变。

**判断标准很具体**：
- 标签已推送但 Release 未创建 → **可以**移动
- Release 已创建 → **必须**发新版本号

---

## 三、发 Release

**`gh` 是 Go 程序，只读环境变量、不读 Windows 系统代理。每个新终端都要先设。**
这台机器上直连 `github.com:443` 会超时。

```powershell
$env:HTTPS_PROXY = 'http://127.0.0.1:7897'
$env:HTTP_PROXY  = 'http://127.0.0.1:7897'
$env:Path += ';C:\Program Files\GitHub CLI'      # gh 不在 PATH 里

gh release create v1.2.0 `
  --title "File Tracker - v1.2.0" `
  --notes-file "notes\v1.2.0.md" `
  "dist\File.Tracker_v1.2.0.exe"
```

### 两个格式上的坑

**标题格式沿用本项目自己的**：`File Tracker - v1.2.0`（带空格与连字符）。
Roboc 用的是 `Roboc_v1.1.0`，**不要照抄那个项目**。

**资产文件名此前四个版本各不相同**：

| 标签 | 资产 |
|---|---|
| v1.0.1 | `File.Tracker.exe` |
| v1.0.2 | `File.Tracker_v1.02.exe`（少一个点） |
| v1.0.3 | `File.Tracker_v1.0.3.exe` |
| v1.1.0 | `File.Tracker_v1.1.exe` |

而 README 承诺的是 `File Tracker.exe`——**和后三个都不符**。
从 v1.2.0 起统一用 **`File.Tracker_v<完整版本号>.exe`**，例如
`File.Tracker_v1.2.0.exe`，并把这一个名字写进 README。
`build.ps1` 产出的是 `dist\File Tracker.exe`，发版前改名。

---

## 四、每次发布后必须做的两件核对

```powershell
# 核对一：线上资产 SHA256 == 本地包
$url = (gh release view v1.2.0 --json assets --jq '.assets[0].url')
Invoke-WebRequest -Uri $url -OutFile $tmp
(Get-FileHash $tmp -Algorithm SHA256).Hash -eq (Get-FileHash $local -Algorithm SHA256).Hash

# 核对二：GitHub 的 main 就是本地 HEAD
git rev-parse HEAD
gh api repos/Neus117/File-Tracker/git/ref/heads/main --jq '.object.sha'
```

**"上传成功"和"线上那份就是这一份"是两件事。** 只有下载回来重算哈希才能确认后者。

**先设代理再跑 `gh`。** 另外：**别用 `gh api` 测连通性**——它未登录时也要求先登录，
输出的是提示而不是结果，很容易把"请先登录"读成"成功"。
要测连通性就用 `curl.exe` 做 A/B 对照（`--proxy` 与 `--noproxy "*"` 各一次）。

---

## 五、发版检查清单

```
[ ] src\file_tracker\core.py 里的 APP_VERSION 已改，并单独提交
[ ] 工作区干净（git status 无输出）
[ ] pwsh -File build.ps1 全绿
[ ] pwsh -File tools/verify_gui.ps1 全绿
[ ] 产物 --version 自报的哈希 == git rev-parse --short=7 HEAD
[ ] 标签**指向代码提交**，不是 README 提交
[ ] 资产已改名为 File.Tracker_v<版本>.exe
[ ] README 里的资产名与"下载运行 XXX.exe"同步更新
[ ] Release 标题格式：File Tracker - v<版本>
[ ] 下载回来核对 SHA256
[ ] GitHub 的 main == 本地 HEAD
```

---

## 六、v1.2.0 发版事故：**"产物自报哈希"这条纪律从未真正成立**

### 现象

v1.2.0 发出后，下载产物执行 `--version`：

```
File Tracker 1.2.0+unknown
```

而**构建是全绿的**。

### 两个叠加的缺陷

**缺陷一：`_build_info.py` 生成在了错误的目录。**

`File-Tracker.spec` 把它写在**仓库根**，于是它是一个**顶层模块**
`_build_info`；而 `core.build_revision()` 读的是
`from ._build_info import ...` —— **包内相对导入**。
路径对不上，`ImportError` 被 `except` 吞掉，于是永远回落到 `"unknown"`。

（spec 里那句注释"只给 `src/` 的话 `_build_info` 可能找不到"，
把因果关系写反了：正因为它是顶层模块才找不到。）

**缺陷二（更严重）：自检是假阳性。**

`build.ps1` 把 `FILE_TRACKER_BUILD_REV` 设进了**自己的进程环境**——
那是 `build_revision()` 的**第 2 号来源**。第 4 步跑 exe 自检时，
exe 从环境变量里读到了哈希，于是

```powershell
if ($reported -notmatch [regex]::Escape($revision)) { throw ... }
```

**恒不触发**。校验看起来在守规则二，实际上什么都没守。

### 修法

1. `_build_info.py` 写进 **`src/file_tracker/`**（包内），
   `hiddenimports` 改成 `file_tracker._build_info`，
   `pathex` 里的 `SPECPATH` 随之删掉。
2. **自检前把 `FILE_TRACKER_BUILD_REV` 从环境里摘掉**，
   跑完再放回（`try/finally`）。测"它自己能不能说清楚自己是谁"，
   就必须在**没有外援**的条件下测。
3. `.gitignore` 补上 `/src/file_tracker/_build_info.py`。

### 教训（比缺陷本身更重要）

> **一个从不失败的校验，等于没有校验。**

改完之后第 4 步立刻**真的失败了**（`+unknown` 被拦下），
这才证明它开始工作。**改完校验，要故意让它失败一次。**

> 顺带：`$psi.EnvironmentVariables` / `$psi.Environment` 这两个属性
> 在 Windows PowerShell 5.1 与 PowerShell 7 上不通用，
> 实测其中一边是 `$null`，会报"不能对 Null 值表达式调用方法"。
> 用 `Remove-Item Env:\<名字>` 更稳。

---

## 七、与本文件同一批被归档的两份文档（2026-10-17）

`docs/` 下原来还有两份**工作文档**，内容是"当前状态的快照" +
"怎么改某个常量"的速查。**它们的有效期都短**（行号会漂、版本号会过期），
而仓库里留着一份会过期的副本，比没有更糟 —— 下一个人会照着它去改。

**已并入 `D:\Coding\DeepSeek 开发经验\`（不在本仓库）：**

| 原文档 | 去处 |
|---|---|
| `docs/调色与排版-改哪里.md` | 项目专属的常量速查与"别再动"的定论 → `projects/File-tracker.md`；其中可复用的判据 → `02-通用开发经验.md` 第三十节 |
| `docs/交接-2026-10-17.md` | 状态部分（含"它当时的判断 vs 后来的实测"对照）→ `projects/File-tracker.md`；交接方法与判据 → `02-通用开发经验.md` 第三十一节 |
| `tools/check_doc_lines.py` | 一并删除 —— 它是**专为**上面第一份文档核对"第 N 行"引用的一次性工具，文档没了它必然失效（而它从来没被任何脚本调用过） |

> **判据：仓库里只留"长期有效"的文档。**
> 状态快照、行号速查这类东西，**要么当场用掉，要么归档到仓库之外** ——
> 它们的正确定位是"开发时的便签"，不是"仓库的一部分"。
>
> 本文件（`RELEASING.md`）能留下，是因为它写的是**流程**（长期有效），
> 而不是"当前是第几版、哪个常量在第几行"（短期有效）。
