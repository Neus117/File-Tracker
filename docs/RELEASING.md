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
