#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
FROM-GLC10 (全球 10 米地表覆盖) 专用农业地块提取与联合国无偏统计流水线
数据集源：鹏城星云 iEarth DataHub (https://data-starcloud.pcl.ac.cn/iearthdata/1)
理论依据：《联合国农业统计遥感手册》(FAO/UNSD UN-Handbook 第 8、11、24、26 章)
==============================================================================
"""

import os
import sys
import argparse
import yaml
import time
import numpy as np

from src.glc10_loader import GLC10Loader
from src.glc10_parcel_segmenter import GLC10ParcelSegmenter
from src.glc10_vector_exporter import GLC10VectorExporter
from src.glc10_unbiased_estimator import GLC10UnbiasedEstimator
from src.glc10_webgis import GLC10WebGISBuilder
from src.glc10_report import GLC10ReportGenerator


def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(base_dir, config_path)
        if os.path.exists(cand):
            config_path = cand

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def run_pipeline(config_path: str = "config.yaml", tif_path: str = None,
                 mode: str = None, output_dir_override: str = None):
    t0 = time.time()
    config = load_config(config_path)

    output_dir = output_dir_override or config.get("paths", {}).get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 88)
    print("🌾 鹏城星云 FROM-GLC10 (全球 10 米地表覆盖) 专用农业地块提取与联合国无偏统计流水线")
    print("   标准依据：联合国粮农组织与统计司 (FAO/UNSD)《农业统计遥感手册》")
    print("=" * 88)

    # 1. 载入 10 米地表覆盖瓦片并提取农情图层
    print("📡 [步骤 1/5] 解析 10 米 FROM-GLC10 地理参考与分类图层...")
    loader = GLC10Loader(config)
    raw_raster, geo_info = loader.load_glc10_raster(tif_path)
    crop_mask, naive_stats = loader.extract_crop_mask(raw_raster)

    total_pixels = raw_raster.size
    crop_pixels = int(np.sum(crop_mask > 0))
    res_m = geo_info.get("resolution_meters", 10.0)
    print(f"   -> 影像规格: {geo_info['width']} × {geo_info['height']} 像元 (空间分辨率: {res_m:.1f}米，坐标系: {geo_info['crs']})")
    print(f"   -> 农情检出: 共识别 {len(naive_stats)} 种农作物类型，累计农作物像元 {crop_pixels:,} 个 (覆盖率: {(crop_pixels/max(total_pixels,1))*100:.1f}%)")
    for code, s in naive_stats.items():
        print(f"      • {s['name']} (代码 {code}): {s['pixels']:,} 像元 | 初测面积: {s['area_mu']:,.1f} 亩 ({s['area_ha']:,.1f} ha)")

    # 2. 10 米专属形态学田埂切分与斑块连通域标记
    print("\n🚜 [步骤 2/5] 执行 10 米专用形态学田埂切分与地块连通域勾勒...")
    segmenter = GLC10ParcelSegmenter(config)
    parcel_id_mask, parcel_list = segmenter.segment_parcels(crop_mask)
    total_parcels = len(parcel_list)
    total_parcel_mu = sum(p["area_mu"] for p in parcel_list)
    print(f"   -> 成功勾勒分离出 {total_parcels} 个独立规整小农地块 (累计净耕地面积: {total_parcel_mu:,.1f} 亩)")
    if total_parcels > 0:
        avg_mu = total_parcel_mu / total_parcels
        print(f"   -> 单块平均面积: {avg_mu:.1f} 亩 (符合小农与集约化农场尺度)")

    # 3. 矢量拓扑平滑与导出 OGC 标准 GeoJSON / CSV 台账
    print("\n📐 [步骤 3/5] 执行 Chaikin 边界拓扑平滑，导出 RFC 7946 标准矢量多边形...")
    exporter = GLC10VectorExporter(config)
    geojson_path, csv_path, summary_csv_path = exporter.export_geojson_and_table(
        parcel_id_mask, parcel_list, geo_info, output_dir
    )
    print(f"   -> 矢量地块边界 GeoJSON: {geojson_path}")
    print(f"   -> 属性台账清单 CSV: {csv_path}")
    if os.path.exists(summary_csv_path):
        print(f"   -> 农情分类汇总台账: {summary_csv_path}")

    # 4. 联合国手册第 24 章无偏面积估计与精度核算
    print("\n📊 [步骤 4/5] 依据联合国第 24 章与《Science Bulletin》先验执行无偏统计核算...")
    estimator = GLC10UnbiasedEstimator(config)
    df_acreage, df_cm = estimator.estimate_unbiased_acreage(crop_mask, total_pixels, output_dir)
    acreage_csv = os.path.join(output_dir, "from_glc10_unbiased_acreage_report.csv")
    print(f"   -> 联合国法定无偏统计报表: {acreage_csv}")

    # 5. 生成纯前端交互式数字农情驾驶舱与出版级决策专报
    print("\n🌐 [步骤 5/5] 生成纯前端交互式数字农情驾驶舱与决策分析专报...")
    webgis = GLC10WebGISBuilder(config)
    html_map_path = os.path.join(output_dir, "from_glc10_parcels_map.html")
    webgis.build_map(geojson_path, html_map_path)
    print(f"   -> 🌐 数字驾驶舱 Web 卫星地图: {html_map_path}")

    reporter = GLC10ReportGenerator(config)
    html_report_path = os.path.join(output_dir, "from_glc10_executive_briefing.html")
    reporter.generate_report(acreage_csv, csv_path, html_report_path)
    print(f"   -> 📑 出版级官方决策专报: {html_report_path} (一键打印/导出 PDF)")

    # 控制台官方台账打印
    print("\n" + "=" * 98)
    print("📊 联合国统计司 (UNSD) / 粮农组织 (FAO) 农作物种植面积无偏统计与精度核算台账")
    print("=" * 98)
    print(f"{'农作物类别':<14} | {'像元初测(亩)':<14} | {'无偏校准面积(亩)':<16} | {'标准误 (SE)':<14} | {'变异系数':<8} | {'用户精度 UA':<12}")
    print("-" * 98)
    for _, row in df_acreage.iterrows():
        se_str = f"±{row['se_analytic_mu']:.1f} 亩"
        cv_str = f"{row['cv_pct']:.2f}%"
        print(f"{row['crop_name']:<14} | {row['naive_area_mu']:<16.1f} | {row['unbiased_calibrated_mu']:<18.1f} | {se_str:<16} | {cv_str:<10} | {row['users_accuracy']:<12}")
    print("-" * 98)
    print(f"⏱️ 全流程总耗时: {time.time() - t0:.2f} 秒 · 系统处理就绪！\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FROM-GLC10 (10米地表覆盖) 专用农业地块提取流水线")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径 (默认: config.yaml)")
    parser.add_argument("--tif", default=None, help="指定的 10 米 FROM-GLC10 GeoTIFF 影像路径")
    parser.add_argument("--mode", choices=["synthetic", "geotiff"], default=None, help="运行模式")
    parser.add_argument("--output-dir", default=None, help="成果输出目录")
    parser.add_argument("--self-check", action="store_true", help="执行自动化健康检查与全量测试")
    args = parser.parse_args()

    if args.self_check:
        import run_tests
        run_tests.main()
        sys.exit(0)

    run_pipeline(
        config_path=args.config,
        tif_path=args.tif,
        mode=args.mode,
        output_dir_override=args.output_dir
    )
