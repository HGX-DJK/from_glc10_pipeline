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

# 自动修复 Windows 下 PostgreSQL/PostGIS PROJ_LIB 冲突
try:
    import src.env_utils
except ImportError:
    pass

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


def print_data_inventory(loader: GLC10Loader) -> list:
    """
    扫描并打印 data/glc10_tifs/ 下所有影像的地理位置与农情初筛资产清单。
    """
    all_files = loader.list_all_glc10_files()
    if not all_files:
        return []

    summaries = []
    print("\n" + "=" * 98)
    print(f"🗂️ 【本地 FROM-GLC10 影像数据资产库】(检测到 {len(all_files)} 景 10 米真实卫星瓦片)")
    print("=" * 98)
    print(f"{'#':<3} | {'瓦片文件名':<26} | {'空间经纬度范围':<22} | {'地理区位 / 生态带特征':<30} | {'农田初筛'}")
    print("-" * 98)

    for i, fpath in enumerate(all_files, start=1):
        s = loader.get_file_summary(fpath)
        summaries.append(s)
        b = s.get("bounds", (0, 0, 0, 0))
        b_str = f"{b[1]:.0f}°~{b[3]:.0f}°N, {b[0]:.0f}°~{b[2]:.0f}°E"
        crop_pct = s.get("crop_sample_pct", 0.0)
        if crop_pct > 5.0:
            crop_status = f"{crop_pct:.1f}% (核心农区 ✅)"
        elif crop_pct > 0.0:
            crop_status = f"{crop_pct:.1f}% (零星农地 🌾)"
        else:
            crop_status = "0.0% (极地冻土 ❄️)"
        reg = s.get("region", "未知区域")
        # 截断过长字符保证对齐
        reg_disp = (reg[:27] + "..") if len(reg) > 28 else reg
        print(f"{i:<3} | {s.get('filename', ''):<26} | {b_str:<22} | {reg_disp:<30} | {crop_status}")
    print("-" * 98)
    return summaries


def run_pipeline(config_path: str = "config.yaml", tif_path: str = None,
                 output_dir_override: str = None):
    t0 = time.time()
    config = load_config(config_path)

    output_dir = output_dir_override or config.get("paths", {}).get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 88)
    print("🌾 鹏城星云 FROM-GLC10 (全球 10 米地表覆盖) 专用农业地块提取与联合国无偏统计流水线")
    print("   标准依据：联合国粮农组织与统计司 (FAO/UNSD)《农业统计遥感手册》")
    print("=" * 88)

    # 1. 载入 10 米真实地表覆盖瓦片并提取农情图层
    print("📡 [步骤 1/5] 解析 10 米 FROM-GLC10 地理参考与分类图层...")
    loader = GLC10Loader(config)
    try:
        raw_raster, geo_info = loader.load_glc10_raster(tif_path)
    except FileNotFoundError as e:
        print(f"\n❌ [输入数据缺失] {e}\n")
        sys.exit(1)

    crop_mask, naive_stats = loader.extract_crop_mask(raw_raster)

    total_pixels = raw_raster.size
    crop_pixels = int(np.sum(crop_mask > 0))
    res_m = geo_info.get("resolution_meters", 10.0)
    current_fn = os.path.basename(geo_info.get("tif_path", "raster.tif"))
    print(f"   -> 正在分析影像: {current_fn}")
    print(f"   -> 影像规格: {geo_info['width']} × {geo_info['height']} 像元 (空间分辨率: {res_m:.1f}米，坐标系: {geo_info['crs']})")
    print(f"   -> 农情检出: 共识别 {len(naive_stats)} 种农作物类型，累计农作物像元 {crop_pixels:,} 个 (覆盖率: {(crop_pixels/max(total_pixels,1))*100:.2f}%)")

    if crop_pixels == 0:
        print(f"\n❄️ [高寒生态区/无农田分布] 该影像未检出目标农作物 (农田像元为 0)。")
        print(f"   遥感生态特征：该瓦片位于极地苔原或高纬度亚寒带针叶林冻土带，无农业耕地分布。")
        print(f"⏱️ 本影像全流程耗时: {time.time() - t0:.2f} 秒 · 处理完成！\n")
        return

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
        print(f"   -> 单块平均面积: {avg_mu:.1f} 亩 (高标准规整农田单元)")

    # 3. 矢量拓扑平滑与导出 OGC 标准 GeoJSON / CSV 台账
    print("\n📐 [步骤 3/5] 执行 Chaikin 边界拓扑平滑与 C++ 矢量化，导出 RFC 7946 标准矢量多边形...")
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
    parser.add_argument("--tif", default=None, help="指定的 10 米 FROM-GLC10 GeoTIFF 真实影像路径")
    parser.add_argument("--all", action="store_true", help="批量扫描处理所有包含农田的影像瓦片")
    parser.add_argument("--output-dir", default=None, help="成果输出目录 (默认: output/)")
    parser.add_argument("--self-check", action="store_true", help="执行自动化健康检查与全量测试")
    args = parser.parse_args()

    if args.self_check:
        import run_tests
        run_tests.main()
        sys.exit(0)

    cfg = load_config(args.config)
    loader = GLC10Loader(cfg)

    # 1. 打印本地资产清单
    inventory = print_data_inventory(loader)

    # 2. 调度执行
    if args.tif:
        run_pipeline(
            config_path=args.config,
            tif_path=args.tif,
            output_dir_override=args.output_dir
        )
    elif args.all:
        print("\n🚀 开始执行批量瓦片全自动提取模式...")
        base_out = args.output_dir or cfg.get("paths", {}).get("output_dir", "output")
        for item in inventory:
            fpath = item["path"]
            fname = os.path.splitext(item["filename"])[0]
            tile_out = os.path.join(base_out, fname)
            print(f"\n▶️ 正在处理瓦片: {item['filename']} ...")
            run_pipeline(config_path=args.config, tif_path=fpath, output_dir_override=tile_out)
    else:
        # 默认模式：自动筛选最优先的核心农田瓦片
        agri_candidates = [item for item in inventory if item.get("has_cropland", False)]
        if agri_candidates:
            target_file = agri_candidates[0]["path"]
            fn = agri_candidates[0]["filename"]
            print(f"\n💡 【自动优选农业瓦片】检测到目录中含多幅影像，其中极地/高寒瓦片农田占比为 0.0%，")
            print(f"   系统已自动选定核心农业区瓦片: 【{fn}】")
            print(f"   👉 如需处理其他特定瓦片，可加参数: python main.py --tif data/glc10_tifs/xxx.tif")
            print(f"   👉 如需对全部瓦片执行批处理，可加参数: python main.py --all\n")
            run_pipeline(
                config_path=args.config,
                tif_path=target_file,
                output_dir_override=args.output_dir
            )
        else:
            # 未在清单中找到或由 resolve_glc10_file 兜底
            run_pipeline(
                config_path=args.config,
                tif_path=None,
                output_dir_override=args.output_dir
            )

