# AGENTS.md · 在这个仓库里干活的规定

面向任何接手本项目的 AI（豆包 / Codex / DeepSeek / Claude Code / 本机 WorkBuddy）。
人读的话，看 `README.md`。

## 1. 作图只走 figlab，不自建脚本

用户拿数据来要图时，**默认流程就是本项目**：

```
原始文件 → datasets/<数据集ID>/raw/sources/ → ingest → 建图 → 导出 PDF 到桌面
```

- 不要另写 `plot_xxx.py` 之类的临时 matplotlib 脚本出图（一次性的也不写）。
  唯一例外：figlab 确实做不到的能力，且用户明确同意。
- 默认入口一条命令：`python scripts/new_figure.py <数据目录> --kind eis`
  （先 `--dry-run` 看计划）。它会 ingest → build_spec → 导出到桌面。
  目前只有 `eis` 谱型能出图；`photothermal` 只有数据层，脚本会明确提示而不是乱画。
- 不要手改 `working.csv`；要改数据走平台（表格 / 框选删点 / 平移），有 ledger 留痕。
- 出图前先看 `figures.json` 里有没有现成的图，能复用就不新建。

## 2. 新数据进站

1. 数据集 ID = `<类别>_<YYYYMMDD>`，日期取**数据本身的日期**，例：`eis_20261107`、
   `photothermal_20261111`、`cv_20261201`。名字里的 8 位日期会成为成品文件名前缀。
2. 原始文件（CHI 的 csv/bin、带表头的 txt）丢进 `datasets/<ID>/raw/sources/`。
3. `Dataset(<ID>, <spectrum>).ingest(...)` 生成 `raw_long.csv`（只读快照）+ `working.csv`（工作副本）。
4. 建图：`build_spec(id, dataset, preset="inhouse")` → 在页面或 `specs/<id>.json` 里调。
5. 导出：桌面 `FigLab\<数据日期><类别>作图\` 下只放 pdf / pptx / .figlab。

**命名铁律**：`data_date()` 定完写进 `export.name_date` 就冻死；同一份数据隔几天再导，
必须是同一个文件夹、同一个文件名（同名覆盖）。只有用户手动改名才动。

## 3. 风格怎么改：用户说什么 → 改哪里

用户会直接说人话（"字大点""线粗点""图例挪右上""换成横版"），**不要反问"要改哪个参数"**，
按下表动手，改完告诉他效果。

| 用户说 | 改哪个字段 | 作用范围 |
|---|---|---|
| 以后所有图都这样 | `figlab/spec/presets/inhouse.json` | 全局默认（新图继承） |
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

- `style.spines` 固定 `all`：四边框全画，不做只留左下两条的样式；
- `style.tick_dir` 固定 `in`：刻度朝内；
- `legend.show` 固定 `false`：不用图例框，曲线身份靠**末端同色单字母**（A/B/C…）；
- 符号不用 `x + * 星形 菱形 五边形` 这类线符号，用实心/开口的圆方三角。

用户若要求突破其中某条，先说明这是投稿规范、改了可能被审稿人挑，确认后再动。

改完必须过校验：`validate(spec)` 一次报出全部问题；不合格不许导出。
`x`/`y` 轴标题必须带单位（Ω / s / °C / mA cm⁻² 等），禁止 `x`/`y` 这种占位。

## 4. 路径与数据

- 规格里的 `working_csv` / `export.dir` 一律**相对项目根**（`datasets/...`、`outputs/...`），
  用 `paths.portable()` 写、`paths.absolute()` 读。不要写死盘符，别人 clone 要能跑。
- 桌面成品目录、用户手填的 PPT 路径是绝对路径，它们本来就在项目外。
- 数据来源记 `paths.display_source()` 的写法（`~/Desktop/...`），不写用户名。

## 5. 改完代码要自证

```bash
python tests/acceptance.py          # 总验收（§八 / §九）
python tests/layer1_data.py …       # 对应层的回归
node  tests/ui_smoke.mjs 8778       # 真实浏览器交互（需 Edge/Chrome）
```

- 测试不许碰用户的真实图：要改规格的，跑前存原字节、`finally` 原样写回。
- 交付时给数字（几何/点数/标签重叠），不要用"看起来没问题"。
