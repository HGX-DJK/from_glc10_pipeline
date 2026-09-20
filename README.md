# FROM-GLC10 (全球 10 米地表覆盖) 专用农业地块提取与联合国无偏统计流水线

本子工程专为**鹏城星云 iEarth DataHub（[https://data-starcloud.pcl.ac.cn/iearthdata/1](https://data-starcloud.pcl.ac.cn/iearthdata/1)）**发布的 **10-m Resolution Global Land Cover in 2017 (FROM-GLC10)** 数据集设计。

遵循《联合国农业统计遥感手册》（FAO/UNSD UN-Handbook 第 8、11、24、26 章）国际官方规程，实现从 10 米地表覆盖瓦片到**规整农田边界矢量多边形（GeoJSON）**、**农机适宜度评估**、**联合国面积加权无偏统计（Olofsson 2014）**及**数字农情 WebGIS 驾驶舱**的一站式全自动交付。

---

## 🚀 为什么使用 FROM-GLC10 数据集？

| 核心维度 | 传统 30 米 Landsat 影像 | 本系统使用的 10 米 FROM-GLC10 |
| :--- | :--- | :--- |
| **空间分辨率** | 30 米（900㎡/像元），田埂完全被吞没，地块相互粘连 | **10 米（100㎡/像元）**，机耕道与细窄田埂清晰可辨 |
| **分类成熟度** | 缺少地面样本时易误判（如山体向阳面常绿树误判为作物） | **清华大学宫鹏教授团队标定**，发表于《Science Bulletin》，全球高精度验证 |
| **农田分类细度** | 只能粗分大田 | **明确细分：水稻(11)、设施温室大棚(12)、大田旱作(13)、果园(24)、翻耕裸地(94)** |
| **无偏统计先验** | 缺乏误差矩阵，易产生数学外推失真 | **内置论文验证混淆矩阵**，直接带入联合国第 24 章无偏推算公式，闭式标准误收敛 |

---

## 📥 如何从 iEarth DataHub 下载数据并使用

1. 打开数据集页面：[https://data-starcloud.pcl.ac.cn/iearthdata/1](https://data-starcloud.pcl.ac.cn/iearthdata/1)
2. 检索并下载您所关注的农区瓦片（瓦片以大约每 2° 经纬度分块命名，例如左下角整数字 `E116N35.tif`）；
3. 将下载得到的 `.tif` 文件拷贝放入本项目目录：
   ```text
   from_glc10_pipeline/data/glc10_tifs/
   ```
4. 终端执行运行命令即可！

---

## 💻 快速运行指南

### 1. 一键运行（自动识别瓦片）
```bash
python main.py
```
> 若目录下尚未放入真实 `.tif` 瓦片，系统会自动启用内置的高保真 10 米基准农情场景（含水稻、大棚、旱作、果园与水系道路）进行开箱即测。

### 2. 指定任意外部 GeoTIFF 瓦片运行
```bash
python main.py --tif data/glc10_tifs/your_tile.tif
```

### 3. 一键执行全系统自动化健康测试
```bash
python run_tests.py
```

---

## 📂 输出成果清单 (`output/`)

每次运行完成后，系统将在 `output/` 目录下生成全套统计调查交付成果：

1. **`from_glc10_parcels.geojson`**：
   * 严格遵循 RFC 7946 标准的 WGS84 `[lon, lat]` 多边形矢量图斑，经 Chaikin 拓扑平滑消除了 10 米栅格阶梯锯齿；
   * 可直接拖入 QGIS、ArcGIS、Google Earth 或 Mapbox 中秒级加载。
2. **`from_glc10_parcels_attribute_table.csv`**：
   * 各独立地块的台账清单：含地块编号、农作物代码与名称、净耕地面积（亩/公顷/㎡）、物理周长、几何紧凑度、农机适宜度评级（优/良/中/碎）以及中心地理坐标。
3. **`from_glc10_crop_summary.csv`**：
   * 分作物类别（水稻、大棚、旱作、果园）的汇总面积、块数分布与集中度比例。
4. **`from_glc10_unbiased_acreage_report.csv`**：
   * 联合国粮农组织与统计司法定直报口径的**去偏无偏种植面积总表**，包含解析标准误（SE）、变异系数（CV）、95% 置信区间与系统田埂偏差修正量。
5. **`from_glc10_parcels_map.html`**：
   * **数字农情纯前端交互式 WebGIS 驾驶舱**，双击任意浏览器即可打开，支持图层按水稻/大棚等作物筛选、地块悬停弹窗与面积统计。
6. **`from_glc10_executive_briefing.html`**：
   * **出版级单文件 HTML 官方决策专报**，内嵌核心 KPI 四格看板、联合国 Table 2 混淆矩阵与 Top 10 主力地块台账，支持一键浏览器排版打印或导出 A4 PDF。
