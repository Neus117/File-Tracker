# 抓图留档（探针跑出来的画面）

这里放**诊断时抓下来的画面**，不是构建产物。

* 生成它们的探针：`probe_row_paint_pixels.py`、`probe_user_shape.py`、
  `probe_real_open_pixels.py`、`_crop_shot.py`
* 抓取方式：`PrintWindow` 打在 `wx.ListCtrl` 上 —— **本环境里唯一可信的取像素方式**
  （理由与三条使用规矩见上一级 `README.md` 的「先读这两条」）

## 文件

| 文件 | 是什么 |
|---|---|
| `crop-blue-row-user-shape-A.png` | **选中那一行**的裁剪（按用户配置的形状跑出来的） |
| `crop-blue-row-open-after.png` | 同上，另一场景（新记录落在视口底部） |
| `user-shape-A.png` / `user-shape-B.png` | 完整画面（用户配置形状：path 升序 + 视角居中） |
| `open-before.png` / `open-after.png` / `open-after-live.png` | 从导航窗格打开的前后对照 |
| `real-open-*.png` | **真的**启动资源管理器之后（不换桩）的画面 |

## 这一批图证明什么

`crop-blue-row-*.png` 里那一条 `#0078D7`：
**"选中行确实被画成了系统选中蓝"**，而且是在
`_apply_selection_highlight()` 里画的（见 `paint-trace.txt` 的调用栈）。

它推翻的是**"程序把颜色设错了"这一整类猜想** ——
下一次有人怀疑"高亮没画出来"时，先看一眼这两张图：

```bash
# 不用看图也能核对（图在预览里可能被重采样成白色，所以以像素统计为准）
python tools/probes/_crop_shot.py
# 输出形如：蓝色行像素所在 y = [238]..[271]（共 34 行）  主色 = #0078D7:77%
```

⚠️ **不要靠肉眼看整张 PNG 下结论**：这个环境的图片预览会把整张图
重采样/压平（1030×770 的图看起来是一片白，而像素统计明明有 90% 是蓝的）。
**以 `_crop_shot.py` 的统计为准。**

## 往里加图的规矩

* 文件名要能看出**场景**（`open-after.png` = 从导航窗格打开之后），
  不要用 `shot1.png` 这种
* 探针里凡是 `SaveFile` 到这里的，都要在它自己的 docstring 里写明
  "这张图证明什么"
