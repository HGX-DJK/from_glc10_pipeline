"""
FROM-GLC10 规范 10 米地表覆盖基准仿真景观生成器。
用于系统在未挂载外部真实 GeoTIFF 瓦片时的开箱自测、算法校验与回归测试。
构建包含水稻田(11)、设施温室(12)、大田旱作(13)、果园(24)、道路水体(60)与聚落(80)的高拟真农情场景。
"""

import os
import numpy as np

try:
    import rasterio
    from rasterio.transform import from_origin
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


class GLC10SyntheticGenerator:
    def __init__(self, height: int = 500, width: int = 500, res_meters: float = 10.0):
        self.height = height
        self.width = width
        self.res_meters = res_meters
        # 默认模拟华北-黄淮平原优质粮仓基地 (E 116.5°, N 35.5°)
        self.origin_lon = 116.50
        self.origin_lat = 35.50
        # 10米对应经纬度度数估算 (赤道1度≈111,320米，纬度35°下经度1度≈91,000米)
        self.res_deg_y = self.res_meters / 111320.0
        self.res_deg_x = self.res_meters / (111320.0 * np.cos(np.radians(self.origin_lat)))

    def generate_synthetic_glc10_array(self) -> np.ndarray:
        """
        生成符合 FROM-GLC10 编码的整图栅格矩阵 (uint8):
        - 0: 背景/田埂
        - 11: 水稻田 (Rice)
        - 12: 设施温室大棚 (Greenhouse)
        - 13: 旱地大田农作物 (Other Crops)
        - 24: 经济果园 (Orchard)
        - 60: 河流沟渠 (Water)
        - 80: 农村聚落与机耕主干道 (Impervious)
        """
        grid = np.zeros((self.height, self.width), dtype=np.uint8)

        # 1. 铺设天然森林与背景基底 (Code 20)
        h, w = self.height, self.width
        grid[0:max(int(h * 0.08), 3), :] = 20
        grid[:, 0:max(int(w * 0.06), 3)] = 20

        # 2. 绘制主干水系河流 (Code 60) 与道路 (Code 80)
        for r in range(h):
            c_river = int(w * 0.5 + w * 0.08 * np.sin(r / max(h * 0.15, 1.0)))
            r_w = max(2, int(w * 0.015))
            if 0 <= c_river < w - r_w:
                grid[r, c_river:c_river + r_w] = 60

            c_road = int(w * 0.28 + w * 0.04 * np.cos(r / max(h * 0.2, 1.0)))
            if 0 <= c_road < w - 2:
                grid[r, c_road:c_road + 2] = 80

        # 贯穿东西的农村主干道
        r_mid = int(h * 0.48)
        grid[r_mid:r_mid + 2, :] = 80

        # 3. 规划现代规整大田旱作区 (Code 13，分布在西北片区)
        step_r = max(8, int(h * 0.08))
        step_c = max(10, int(w * 0.1))
        for r_start in range(int(h * 0.1), int(h * 0.45), step_r):
            for c_start in range(int(w * 0.08), int(w * 0.45), step_c):
                r_end = min(r_start + int(step_r * 0.8), int(h * 0.45))
                c_end = min(c_start + int(step_c * 0.8), int(w * 0.45))
                if r_end > r_start and c_end > c_start:
                    grid[r_start:r_end, c_start:c_end] = 13

        # 4. 规划水网湿地水稻种植示范区 (Code 11，分布在东北片区)
        for r_start in range(int(h * 0.1), int(h * 0.45), step_r):
            for c_start in range(int(w * 0.58), int(w * 0.95), step_c):
                r_end = min(r_start + int(step_r * 0.8), int(h * 0.45))
                c_end = min(c_start + int(step_c * 0.8), int(w * 0.95))
                if r_end > r_start and c_end > c_start:
                    grid[r_start:r_end, c_start:c_end] = 11

        # 5. 规划高附加值设施农业温室大棚区 (Code 12，西南片区)
        step_r_gh = max(5, int(h * 0.05))
        step_c_gh = max(6, int(w * 0.06))
        for r_start in range(int(h * 0.52), int(h * 0.82), step_r_gh):
            for c_start in range(int(w * 0.08), int(w * 0.45), step_c_gh):
                r_end = min(r_start + int(step_r_gh * 0.75), int(h * 0.82))
                c_end = min(c_start + int(step_c_gh * 0.75), int(w * 0.45))
                if r_end > r_start and c_end > c_start:
                    grid[r_start:r_end, c_start:c_end] = 12

        # 6. 规划平缓台地经济果园基地 (Code 24，东南片区)
        for r_start in range(int(h * 0.52), int(h * 0.85), step_r):
            for c_start in range(int(w * 0.55), int(w * 0.95), step_c):
                r_end = min(r_start + int(step_r * 0.8), int(h * 0.85))
                c_end = min(c_start + int(step_c * 0.8), int(w * 0.95))
                if r_end > r_start and c_end > c_start:
                    grid[r_start:r_end, c_start:c_end] = 24

        # 7. 规划村庄聚落中心 (Code 80)
        grid[int(h * 0.86):int(h * 0.95), int(w * 0.35):int(w * 0.55)] = 80

        # 8. 局部季节性休耕裸耕地 (Code 94)
        grid[int(h * 0.86):int(h * 0.95), int(w * 0.08):int(w * 0.28)] = 94

        return grid

    def save_synthetic_geotiff(self, output_tif_path: str) -> str:
        """保存标准带 WGS84 空间参考的 10 米 GeoTIFF 影像。"""
        os.makedirs(os.path.dirname(output_tif_path), exist_ok=True)
        data = self.generate_synthetic_glc10_array()

        if HAS_RASTERIO:
            transform = from_origin(self.origin_lon, self.origin_lat, self.res_deg_x, self.res_deg_y)
            profile = {
                "driver": "GTiff",
                "height": self.height,
                "width": self.width,
                "count": 1,
                "dtype": rasterio.uint8,
                "crs": "EPSG:4326",
                "transform": transform,
                "compress": "deflate",
                "nodata": 0
            }
            with rasterio.open(output_tif_path, "w", **profile) as dst:
                dst.write(data, 1)
        else:
            # 备用：若无 rasterio，直接写入单通道 numpy 存档或提示
            np.save(output_tif_path.replace(".tif", ".npy"), data)

        return output_tif_path

    def get_geo_info(self) -> dict:
        """返回场景空间元数据字典。"""
        return {
            "crs": "EPSG:4326",
            "is_geographic": True,
            "resolution_x": self.res_deg_x,
            "resolution_y": self.res_deg_y,
            "resolution_meters": self.res_meters,
            "width": self.width,
            "height": self.height,
            "origin_lon": self.origin_lon,
            "origin_lat": self.origin_lat,
            "bounds": (
                self.origin_lon,
                self.origin_lat - self.height * self.res_deg_y,
                self.origin_lon + self.width * self.res_deg_x,
                self.origin_lat
            )
        }
