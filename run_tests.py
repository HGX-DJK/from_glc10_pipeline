#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FROM-GLC10 农业地块提取流水线自动化全量测试与健康自检套件。
测试完全基于纯内存或临时夹具运行，零外部脏数据残留。
"""

import os
import sys
import unittest
import numpy as np

# 将工程根目录添加到模块搜索路径
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# 自动修复 Windows 下 PostgreSQL/PostGIS PROJ_LIB 冲突
try:
    from src.env_utils import sanitize_proj_gdal_env
    sanitize_proj_gdal_env()
except ImportError:
    pass

import rasterio
from rasterio.transform import from_origin
from src.glc10_loader import GLC10Loader
from src.glc10_parcel_segmenter import GLC10ParcelSegmenter
from src.glc10_vector_exporter import GLC10VectorExporter, chaikin_smooth, haversine_distance
from src.glc10_unbiased_estimator import GLC10UnbiasedEstimator
from main import run_pipeline, load_config


def create_in_memory_mock_raster(height=120, width=120):
    """
    构造纯内存标准测试栅格（完全遵循 FROM-GLC10 官方规范）：
    - 10: 耕地/农田 (Cropland)
    - 20: 森林 (Forest)
    - 60: 水体河流 (Water)
    - 80: 道路聚落 (Impervious)
    """
    grid = np.full((height, width), 20, dtype=np.uint8)  # 背景森林
    # 农田区 (代码 10)
    grid[15:105, 15:105] = 10
    # 道路切分 (代码 80)
    grid[58:62, :] = 80
    grid[:, 58:62] = 80
    # 局部水渠 (代码 60)
    grid[85:88, 15:58] = 60
    return grid


def create_temp_geotiff(file_path: str, height=120, width=120):
    """在指定路径创建一个轻量临时测试 GeoTIFF"""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    grid = create_in_memory_mock_raster(height, width)
    # 设定测试参考坐标 (E 106.5°, N 34.5° 关中天水农业区)
    transform = from_origin(106.50, 34.50, 0.0001, 0.0001)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": rasterio.uint8,
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": 0
    }
    with rasterio.open(file_path, "w", **profile) as dst:
        dst.write(grid, 1)
    return file_path


class TestGLC10Pipeline(unittest.TestCase):
    def setUp(self):
        self.config = load_config("config.yaml")

    def test_mock_raster_structure(self):
        """测试标准内存栅格构造器包含真实耕地(10)与背景地类"""
        arr = create_in_memory_mock_raster(100, 100)
        self.assertEqual(arr.shape, (100, 100))
        unique_vals = np.unique(arr)
        self.assertTrue(10 in unique_vals, "应包含真实 FROM-GLC10 官方耕地代码 10")
        self.assertTrue(20 in unique_vals, "应包含森林背景代码 20")
        self.assertTrue(80 in unique_vals, "应包含道路阻断代码 80")

    def test_crop_mask_extraction(self):
        """测试从地表覆盖全景中精准抽取耕地(10)掩膜与初测面积"""
        loader = GLC10Loader(self.config)
        raw = create_in_memory_mock_raster(100, 100)
        mask, stats = loader.extract_crop_mask(raw)

        self.assertEqual(mask.shape, raw.shape)
        # 验证森林(20)、水体(60)与道路(80)已被置零过滤
        self.assertEqual(np.sum(mask == 20), 0)
        self.assertEqual(np.sum(mask == 60), 0)
        self.assertEqual(np.sum(mask == 80), 0)
        # 验证目标作物代码 10 成功检出
        self.assertIn(10, stats)
        self.assertGreater(stats[10]["pixels"], 0)

    def test_10m_parcel_segmentation(self):
        """测试 10 米形态学田埂切分与斑块连通域标记"""
        segmenter = GLC10ParcelSegmenter(self.config)
        raw = create_in_memory_mock_raster(120, 120)
        loader = GLC10Loader(self.config)
        mask, _ = loader.extract_crop_mask(raw)

        parcel_id_mask, parcel_list = segmenter.segment_parcels(mask)
        self.assertEqual(parcel_id_mask.shape, mask.shape)
        self.assertGreater(len(parcel_list), 0, "应提取出独立农田地块")

        # 检验地块属性完整性
        first = parcel_list[0]
        self.assertIn("parcel_id", first)
        self.assertEqual(first["dominant_crop_code"], 10)
        self.assertIn("area_mu", first)
        self.assertGreater(first["area_mu"], 0.0)

    def test_chaikin_smooth_and_distance(self):
        """测试 Chaikin 拓扑平滑算法与大圆大地距离计算"""
        # 测试大地大圆距离
        dist = haversine_distance(106.0, 34.0, 106.0, 34.01)
        self.assertGreater(dist, 1000.0)
        self.assertLess(dist, 1200.0)

        # 测试平滑几何
        square = np.array([[0, 0], [0, 10], [10, 10], [10, 0]])
        smoothed = chaikin_smooth(square, iterations=2)
        self.assertEqual(len(smoothed), 16)

    def test_unbiased_estimation(self):
        """测试基于 Science Bulletin 官方精度先验的联合国无偏估计"""
        estimator = GLC10UnbiasedEstimator(self.config)
        raw = create_in_memory_mock_raster(100, 100)
        loader = GLC10Loader(self.config)
        mask, _ = loader.extract_crop_mask(raw)

        test_out = os.path.join(project_dir, "output", "test_unbiased")
        df_report, df_cm = estimator.estimate_unbiased_acreage(mask, 10000, test_out)

        self.assertFalse(df_report.empty)
        self.assertIn("unbiased_calibrated_mu", df_report.columns)
        self.assertIn("se_analytic_mu", df_report.columns)
        self.assertIn("cv_pct", df_report.columns)

        # 变异系数 CV 应处于受控健康区间 (< 30%)
        for cv in df_report["cv_pct"]:
            self.assertLess(cv, 30.0, f"CV 应受控在 30% 以内，当前为 {cv}%")

    def test_full_pipeline_e2e(self):
        """测试端到端全流程运行（临时真实 GeoTIFF -> 分割 -> 矢量化 -> 无偏统计 -> WebGIS 与专报）"""
        test_out = os.path.join(project_dir, "output", "test_e2e")
        temp_tif = os.path.join(test_out, "temp_test_tile.tif")
        create_temp_geotiff(temp_tif, 120, 120)

        try:
            run_pipeline(
                config_path="config.yaml",
                tif_path=temp_tif,
                output_dir_override=test_out
            )

            geojson_file = os.path.join(test_out, "from_glc10_parcels.geojson")
            csv_file = os.path.join(test_out, "from_glc10_parcels_attribute_table.csv")
            webgis_file = os.path.join(test_out, "from_glc10_parcels_map.html")
            report_file = os.path.join(test_out, "from_glc10_executive_briefing.html")

            self.assertTrue(os.path.exists(geojson_file), "应生成 GeoJSON 矢量成果")
            self.assertTrue(os.path.exists(csv_file), "应生成属性台账 CSV")
            self.assertTrue(os.path.exists(webgis_file), "应生成 WebGIS 驾驶舱")
            self.assertTrue(os.path.exists(report_file), "应生成官方决策专报")
        finally:
            if os.path.exists(temp_tif):
                os.remove(temp_tif)


def main():
    print("=" * 80)
    print("🌾 FROM-GLC10 (10米) 农业地块提取流水线：自动化全量测试与健康自检")
    print("=" * 80)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGLC10Pipeline)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n✨ [ALL PASS] FROM-GLC10 全系统测试全部通过！系统处于健康就绪状态。")
        return 0
    else:
        print("\n❌ 部分测试未通过，请检查上方日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
