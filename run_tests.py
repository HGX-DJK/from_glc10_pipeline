#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FROM-GLC10 农业地块提取流水线自动化全量测试与健康自检套件。
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

from src.glc10_synthetic import GLC10SyntheticGenerator
from src.glc10_loader import GLC10Loader
from src.glc10_parcel_segmenter import GLC10ParcelSegmenter
from src.glc10_vector_exporter import GLC10VectorExporter, chaikin_smooth, haversine_distance
from src.glc10_unbiased_estimator import GLC10UnbiasedEstimator
from main import run_pipeline, load_config


class TestGLC10Pipeline(unittest.TestCase):
    def setUp(self):
        self.config = load_config("config.yaml")

    def test_synthetic_generation(self):
        """测试 10 米基准农情景观生成器"""
        synth = GLC10SyntheticGenerator(height=100, width=100, res_meters=10.0)
        arr = synth.generate_synthetic_glc10_array()
        self.assertEqual(arr.shape, (100, 100))
        # 验证包含水稻(11)、大棚(12)、旱作(13)等核心农情类别
        unique_vals = np.unique(arr)
        self.assertTrue(11 in unique_vals, "应包含水稻类别 11")
        self.assertTrue(12 in unique_vals, "应包含设施温室类别 12")
        self.assertTrue(13 in unique_vals, "应包含旱地农作物类别 13")

    def test_crop_mask_extraction(self):
        """测试从地表覆盖全景中精准抽取农作物掩膜与初测面积"""
        loader = GLC10Loader(self.config)
        synth = GLC10SyntheticGenerator(height=80, width=80)
        raw = synth.generate_synthetic_glc10_array()
        mask, stats = loader.extract_crop_mask(raw)

        self.assertEqual(mask.shape, raw.shape)
        # 验证森林(20)与水体(60)已被置零过滤
        self.assertEqual(np.sum(mask == 20), 0)
        self.assertEqual(np.sum(mask == 60), 0)
        self.assertGreater(len(stats), 0, "应统计到农情分类初测数据")

    def test_10m_parcel_segmentation(self):
        """测试 10 米形态学田埂切分与斑块连通域标记"""
        segmenter = GLC10ParcelSegmenter(self.config)
        synth = GLC10SyntheticGenerator(height=120, width=120)
        raw = synth.generate_synthetic_glc10_array()
        loader = GLC10Loader(self.config)
        mask, _ = loader.extract_crop_mask(raw)

        parcel_id_mask, parcel_list = segmenter.segment_parcels(mask)
        self.assertEqual(parcel_id_mask.shape, mask.shape)
        self.assertGreater(len(parcel_list), 0, "应提取出独立农田地块")

        # 检验首个地块属性完整性
        first = parcel_list[0]
        self.assertIn("parcel_id", first)
        self.assertIn("dominant_crop_code", first)
        self.assertIn("area_mu", first)
        self.assertGreater(first["area_mu"], 0.0)

    def test_chaikin_smooth_and_distance(self):
        """测试 Chaikin 拓扑平滑算法与大圆大地距离计算"""
        # 测试距离
        dist = haversine_distance(116.0, 35.0, 116.0, 35.01)
        self.assertGreater(dist, 1000.0)
        self.assertLess(dist, 1200.0)

        # 测试平滑
        square = np.array([[0, 0], [0, 10], [10, 10], [10, 0]])
        smoothed = chaikin_smooth(square, iterations=2)
        self.assertEqual(len(smoothed), 16)

    def test_unbiased_estimation(self):
        """测试基于 Science Bulletin 官方精度先验的联合国无偏估计"""
        estimator = GLC10UnbiasedEstimator(self.config)
        synth = GLC10SyntheticGenerator(height=100, width=100)
        raw = synth.generate_synthetic_glc10_array()
        loader = GLC10Loader(self.config)
        mask, _ = loader.extract_crop_mask(raw)

        test_out = os.path.join(project_dir, "output", "test_unbiased")
        df_report, df_cm = estimator.estimate_unbiased_acreage(mask, 10000, test_out)

        self.assertFalse(df_report.empty)
        self.assertIn("unbiased_calibrated_mu", df_report.columns)
        self.assertIn("se_analytic_mu", df_report.columns)
        self.assertIn("cv_pct", df_report.columns)

        # 变异系数 CV 应处于受控健康区间
        for cv in df_report["cv_pct"]:
            self.assertLess(cv, 30.0, f"CV 应受控在 30% 以内，当前为 {cv}%")

    def test_full_pipeline_e2e(self):
        """测试端到端全流程运行（模拟数据生成 -> 分割 -> 矢量化 -> 无偏统计 -> WebGIS 与专报）"""
        test_out = os.path.join(project_dir, "output", "test_e2e")
        run_pipeline(
            config_path="config.yaml",
            mode="synthetic",
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
