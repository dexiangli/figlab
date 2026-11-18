# AGENTS.md · 在这个仓库里干活的规定

面向任何接手本项目的 AI（豆包 / Codex / DeepSeek / Claude Code / 本机 WorkBuddy）。
人读的话，看 `README.md`。

## 1. 在 FigLab 中处理数据并作图

用户拿数据来要图时，先把数据接入 FigLab，使用制图台生成、核验和导出图件。遇到尚未支持的图型，在 FigLab 中新增可复用的处理和绘图模板，保留源数据、计算规则和绘图数据的关联。

个人处理模板随本机使用逐步建立和维护。需要改代码的个人扩展可放在本地分支，公共 GitHub 分支同步通用平台功能。

```
原始数据 → FigLab 数据集和处理模板 → 核验 → 单图或组图 → 导出
```

- 按数据和用途确定曲线、坐标、图例和版式。使用 FigLab 的内置谱型和预设，或扩展制图台模板。
- 首次部署后打开 `/style.html`，让使用者选择字体、配色、字号、轴线与布局，可让他们提供喜欢的参考图。保存到数据根的 `style_settings.json`。后续作图先读这份个人设置，包括外部生成后导入的单图。仓库 `inhouse` 是可选参考方案，黄金比例 8.9×5.5 cm、Arial 7/6.5 pt、金黄淡紫钢蓝玫红；每位使用者可按自己的偏好调整。排版优先考虑约 1.618 的宽高比，按目标期刊栏宽适配。图例放在空白区，关键数值可放在留白小表，显示范围和统计量按谱型与图意确定。
- 已生成的 PNG、JPEG、WebP 可在组图页面用「添加照片」导入。单独交付时按用户需要提供 SVG、PDF 或其他格式。
- 用户要单图时，在项目管理器中按课题归档为单图窗口。只有用户要求拼版或组图时才创建组图窗口，禁止用只含一个面板的组图代替单图。
- 静态图片导入用于用户提供的图件或用户明确要求的排版。由数据生成的图需能从界面追溯绘图数据。交付前在项目树核对文件夹和图窗类型。
- 如果本次任务选用 FigLab 内置渲染，可用 `python scripts/new_figure.py <数据目录> --kind eis` 创建 EIS 图。使用平台数据集时，通过平台编辑 `working.csv`，让改动写入台账。

## 2. 使用内置绘图时的数据进站

1. 数据集 ID = `<类别>_<YYYYMMDD>`，日期取**数据本身的日期**，例：`eis_20261107`、
   `photothermal_20261111`、`cv_20261201`。名字里的 8 位日期会成为成品文件名前缀。
2. 原始文件（CHI 的 csv/bin、带表头的 txt）丢进 `datasets/<ID>/raw/sources/`。
3. `Dataset(<ID>, <spectrum>).ingest(...)` 生成 `raw_long.csv`（只读快照）+ `working.csv`（工作副本）。
4. 建图：`build_spec(id, dataset, preset="inhouse")` → 在页面或 `specs/<id>.json` 里调。
5. 导出：桌面 `FigLab\<数据日期><类别>作图\` 下只放 pdf / pptx / .figlab。

**命名铁律**：`data_date()` 定完写进 `export.name_date` 就冻死；同一份数据隔几天再导，
必须是同一个文件夹、同一个文件名（同名覆盖）。只有用户手动改名才动。

## 3. 如何调整 FigLab 内置图的风格

用户会直接说人话（"字大点""线粗点""图例挪右上""换成横版"），**不要反问"要改哪个参数"**，
按下表动手，改完告诉他效果。

| 用户说 | 改哪个字段 | 作用范围 |
|---|---|---|
| 以后所有图都这样 | `/style.html` 或数据根 `style_settings.json` | 个人默认（新图继承） |
| 就这张图 | `specs/<图ID>.json` 的 `overrides` | 单图覆盖 |
| 图多大 / 横版竖版 | `page.w_cm` `page.h_cm` | 画布物理尺寸 |
| 图框在页面哪、多大 | `layer.left/top/width/height`（百分比） | 版心 |
| 字大小 | `style.tick_pt` `style.title_pt` | 刻度 / 标题 |
| 线粗细、点大小 | `style.line_width_pt` `style.marker_size_pt` | 曲线 |
| 边框粗细 | `style.frame_line_width_pt` | 图框 |
| 换配色 | `palette`（8 位十六进制，按曲线顺序取） | 全图 |
| 连线/散点/平滑 | `style.connect` = `scatter` / `segment` / `smooth` | 曲线 |
| 剔除处断线 / 连起来 | `style.break_gaps` = true / false | 曲线 |
| 坐标范围、刻度间隔 | `axis.x_from/x_to/x_inc`、`y_from/y_to/y_inc` | 坐标轴 |
| 轴标题 | `axis.x_title` `axis.y_title` | 坐标轴 |
| 网格 | `style.grid` | 背景 |
| 导出格式 / 分辨率 | `export.formats` `export.dpi` | 导出 |

**规范硬约束（改了校验会直接拒绝，别动）**

- `style.spines` 用 `left_bottom` 或 `all`，默认左下轴配 `style.tick_dir = out`；
- `legend.show` 保持 `false`；浓度或频率图例由对应谱型生成，其余曲线可用末端同色字母；
- 符号不用 `x + * 星形 菱形 五边形` 这类线符号，用实心/开口的圆方三角。

样式以使用者选定的风格及目标期刊的实际要求为准。

改完必须过校验：`validate(spec)` 一次报出全部问题；不合格不许导出。
`x`/`y` 轴标题必须带单位（Ω / s / °C / mA cm⁻² 等），禁止 `x`/`y` 这种占位。

## 4. 路径与数据

- 规格里的 `working_csv` / `export.dir` 一律**相对项目根**（`datasets/...`、`outputs/...`），
  用 `paths.portable()` 写、`paths.absolute()` 读。不要写死盘符，别人 clone 要能跑。
- 「项目根」在运行时可能是**数据根**：`FIGLAB_DATA_ROOT` 指到别处时，`datasets/`、`specs/`、
  `outputs/`、`history/`、`figures.json` 都在那个目录，代码根只放代码与预设。别把数据写进
  代码目录，也别假设两者是同一个目录。
- 桌面成品目录、用户手填的 PPT 路径是绝对路径，它们本来就在项目外。成品才进桌面，
  平台内部文件（规格、快照、工作副本、核验报告）不进桌面。
- 数据来源记 `paths.display_source()` 的写法（`~/Desktop/...`），不写用户名。

## 5. 改完代码要自证

```bash
python tests/acceptance.py          # 总验收（§八 / §九）
python tests/layer1_data.py …       # 对应层的回归
node  tests/ui_smoke.mjs 8778       # 真实浏览器交互（需 Edge/Chrome）
```

- 测试不许碰用户的真实图：要改规格的，跑前存原字节、`finally` 原样写回。
- 交付时给数字（几何/点数/标签重叠），不要用"看起来没问题"。
