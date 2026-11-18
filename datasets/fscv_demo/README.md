# 多巴胺 FSCV 示例

首次打开 FigLab 的默认数据。浓度为 0.75、1.00、1.50、2.00 μM，每条曲线 3,200 点，电位单位 V、电流单位 nA。

数据来自 Berger et al., *Unveiling Dopamine and Met-Enkephalin Dynamics: Simultaneous Co-Detection in Rat Striatum*, Analytical Chemistry 2025, 97(45), 25032–25046，Figure 1C。

- 论文 https://doi.org/10.1021/acs.analchem.5c03599
- 数据 https://doi.org/10.5281/zenodo.17154734
- 数据作者 Sombers, Leslie; McCarty, Gregory，项目成员 Berger, Jenna; Todorov, Jovica; Turner, Kalynn。
- 许可 CC-BY-4.0 https://creativecommons.org/licenses/by/4.0/

`raw/sources/FSCV_DA_concentration_series.csv` 由公开工作簿 `Figure 1` 的 A–E 列逐行转出。原始工作簿 MD5 为 `b5ec6dcb1119db0393988960044a6b44`。CSV 数值与工作簿逐项一致。长表只转换存储结构。

这是论文图源数据，使用改良锯木架波形。第 1501 点的 1.900 V 到第 1502 点的 1.299 V 为电位跳变，绘图在此断开连接。默认主图显示 −0.43 至 1.02 V 峰区，数据表保留完整扫描数据。峰值小表显示 2.00 μM 的正扫最大电流与回扫最小电流，不额外扣除基线。
