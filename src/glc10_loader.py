"""
FROM-GLC10 瓦片数据读取与农情图层映射模块。
负责解析鹏城星云 iEarth DataHub 下载的 10 米地表覆盖瓦片，
提取空间参考元数据，并根据配置筛选与重映射目标农作物图层。
"""

import os
import glob
import numpy as np

try:
    from src.env_utils import sanitize_proj_gdal_env
    sanitize_proj_gdal_env()
except ImportError:
    pass

try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


class GLC10Loader:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.glc10_cfg = self.config.get("glc10_classes", {})
        self.target_crop_codes = self.glc10_cfg.get("target_crop_codes", {
            10: "耕地/农田 (Cropland)"
        })
        self.background_codes = self.glc10_cfg.get("background_codes", {})
        self.nominal_res = self.config.get("spatial", {}).get("nominal_resolution_meters", 10.0)

    def resolve_glc10_file(self, specified_path: str = None) -> str:
        """
        解析输入 GeoTIFF 路径。
        1. 优先使用用户通过 --tif 显式指定的真实影像路径；
        2. 其次自动扫描 data/glc10_tifs/ 目录下的真实瓦片；
        3. 若均未找到，抛出友好的 FileNotFoundError 指引。
        """
        if specified_path:
            if os.path.exists(specified_path):
                return specified_path
            raise FileNotFoundError(f"指定的 GeoTIFF 影像不存在: {specified_path}")

        geotiff_dir = self.config.get("input_source", {}).get("geotiff_dir", "data/glc10_tifs")
        if not os.path.isabs(geotiff_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cand_dir = os.path.join(base_dir, geotiff_dir)
            if os.path.exists(cand_dir):
                geotiff_dir = cand_dir

        if os.path.exists(geotiff_dir):
            candidates = sorted(glob.glob(os.path.join(geotiff_dir, "*.tif*")))
            real_candidates = [c for c in candidates if "benchmark_demo" not in os.path.basename(c)]
            if real_candidates:
                return real_candidates[0]

        raise FileNotFoundError(
            f"未在目录 '{geotiff_dir}' 下检测到有效的 FROM-GLC10 GeoTIFF (.tif) 影像！\n"
            "👉 请从鹏城星云 iEarth 数据平台 (https://data-starcloud.pcl.ac.cn/iearthdata/1) 下载真实瓦片放入该目录，\n"
            "   或在执行时添加参数: python main.py --tif /path/to/your_tile.tif"
        )

    def load_glc10_raster(self, tif_path: str = None) -> tuple:
        """
        读取 10 米 FROM-GLC10 GeoTIFF 影像。
        返回:
            raw_raster (np.ndarray): 原始地表覆盖类别矩阵 (uint8)
            geo_info (dict): 空间坐标与地理元数据字典
        """
        resolved_path = self.resolve_glc10_file(tif_path)

        if not HAS_RASTERIO:
            raise ImportError("未检测到 rasterio 空间遥感库，请执行 pip install rasterio 安装。")

        with rasterio.open(resolved_path) as src:
            raw_raster = src.read(1)
            crs_str = str(src.crs) if src.crs else "EPSG:4326"
            is_geo = src.crs.is_geographic if src.crs else True

            res_x = abs(src.transform[0])
            res_y = abs(src.transform[4])

            # 分辨率米制折算
            if is_geo:
                # 纬度中心度数转米
                center_lat = (src.bounds.bottom + src.bounds.top) / 2.0
                res_meters_x = res_x * 111320.0 * np.cos(np.radians(center_lat))
                res_meters_y = res_y * 111320.0
                res_meters = float((res_meters_x + res_meters_y) / 2.0)
            else:
                res_meters = float(res_x)

            # 约束标称分辨率在 10 米附近
            if abs(res_meters - 10.0) < 5.0:
                res_meters = 10.0

            geo_info = {
                "tif_path": resolved_path,
                "crs": crs_str,
                "transform": src.transform,
                "bounds": src.bounds,
                "width": src.width,
                "height": src.height,
                "resolution_x": res_x,
                "resolution_y": res_y,
                "resolution_meters": res_meters,
                "is_geographic": is_geo,
                "nodata": src.nodata
            }

        return raw_raster, geo_info

    def extract_crop_mask(self, raw_raster: np.ndarray) -> tuple:
        """
        根据目标农情配置，将原始 FROM-GLC10 栅格转换为农作物分类掩膜。
        - 农田类别：保留真实代码 (10, 11, 12, 13, 24, 94)
        - 非农田/自然背景：全部置为 0
        返回:
            crop_mask (np.ndarray): 净化后的农作物图层矩阵
            stats_dict (dict): 各农情类别的直接像元计数与初测面积
        """
        crop_mask = np.zeros_like(raw_raster, dtype=np.uint8)
        stats_dict = {}
        pixel_area_sqm = self.nominal_res * self.nominal_res  # 10m x 10m = 100 m²

        for code, name in self.target_crop_codes.items():
            match = (raw_raster == int(code))
            cnt = int(np.sum(match))
            if cnt > 0:
                crop_mask[match] = int(code)
                area_sqm = cnt * pixel_area_sqm
                area_mu = area_sqm / (2000.0 / 3.0)  # 1亩 ≈ 666.6667 平方米
                area_ha = area_sqm / 10000.0
                stats_dict[int(code)] = {
                    "name": name,
                    "pixels": cnt,
                    "area_m2": round(area_sqm, 1),
                    "area_mu": round(area_mu, 2),
                    "area_ha": round(area_ha, 2)
                }

        return crop_mask, stats_dict
