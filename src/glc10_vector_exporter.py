"""
FROM-GLC10 矢量边界平滑与 GeoJSON / CSV 属性表导出模块。
实现功能：
1. 基于 trace_grid_boundary 的纯 NumPy 拓扑网格边界跟踪（免除 skimage 依赖）
2. Chaikin 拐角切割拓扑平滑（消除 10 米阶梯锯齿）
3. 严格遵循 RFC 7946 规范生成 WGS84 [lon, lat] 矢量 GeoJSON
4. 计算真实的平面/大地米制周长、紧凑度与农机适宜度评估指标
"""

import os
import json
import numpy as np
import pandas as pd
from src.geometry_utils import trace_grid_boundary, simplify_polygon, chaikin_smooth, haversine_distance


class GLC10VectorExporter:
    def __init__(self, config: dict = None):
        self.config = config or {}
        seg_cfg = self.config.get("segmentation", {})
        self.smooth_boundaries = seg_cfg.get("smooth_boundaries", True)
        self.chaikin_iters = seg_cfg.get("chaikin_iterations", 2)
        self.res_meters = self.config.get("spatial", {}).get("nominal_resolution_meters", 10.0)

    def export_geojson_and_table(self, parcel_id_mask: np.ndarray, parcel_metadata: list,
                                geo_info: dict, output_dir: str) -> tuple:
        """
        将地块图斑导出为标准 GeoJSON 与 CSV 属性台账。
        返回: (geojson_path, csv_path, summary_csv_path)
        """
        os.makedirs(output_dir, exist_ok=True)
        geojson_path = os.path.join(output_dir, "from_glc10_parcels.geojson")
        csv_path = os.path.join(output_dir, "from_glc10_parcels_attribute_table.csv")
        summary_csv_path = os.path.join(output_dir, "from_glc10_crop_summary.csv")

        transform = geo_info.get("transform")
        is_geo = geo_info.get("is_geographic", True)

        features = []
        records = []

        for p_info in parcel_metadata:
            int_id = p_info["int_id"]
            sl = p_info["bbox_slice"]

            sub_mask = (parcel_id_mask[sl] == int_id)
            if not np.any(sub_mask):
                continue

            # 纯 NumPy 栅格边缘拓扑追踪
            ring_pts = trace_grid_boundary(sub_mask)
            if len(ring_pts) < 4:
                continue

            # RDP 拓扑抽稀消除阶梯共线网格点，大幅降低点集规模与文件体积
            ring_pts = simplify_polygon(ring_pts, tolerance=0.5)
            if len(ring_pts) < 4:
                continue

            # 偏移回全景栅格坐标 (row, col)
            row_offset = sl[0].start
            col_offset = sl[1].start
            global_rows = np.array([p[0] + row_offset for p in ring_pts], dtype=float)
            global_cols = np.array([p[1] + col_offset for p in ring_pts], dtype=float)

            # 转换为地理空间坐标 [x, y]
            if transform is not None:
                xs = transform[2] + global_cols * transform[0] + global_rows * transform[1]
                ys = transform[5] + global_cols * transform[3] + global_rows * transform[4]
            else:
                xs = geo_info.get("origin_lon", 116.5) + global_cols * geo_info.get("resolution_x", 0.0001)
                ys = geo_info.get("origin_lat", 35.5) - global_rows * geo_info.get("resolution_y", 0.0001)

            pts_2d = list(zip(xs.tolist(), ys.tolist()))

            # Chaikin 平滑
            if self.smooth_boundaries and len(pts_2d) >= 6:
                pts_2d = chaikin_smooth(pts_2d, iterations=self.chaikin_iters)

            # 计算周长 (米)
            perimeter_m = 0.0
            n_pts = len(pts_2d)
            for i in range(n_pts - 1):
                p1 = pts_2d[i]
                p2 = pts_2d[i + 1]
                if is_geo:
                    perimeter_m += haversine_distance(p1[0], p1[1], p2[0], p2[1])
                else:
                    perimeter_m += float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))

            perimeter_m = max(perimeter_m, 10.0)

            # 计算紧凑度指标 Compactness = 4 * pi * Area / Perimeter^2
            area_m2 = p_info["area_m2"]
            compactness = float(4.0 * np.pi * area_m2 / (perimeter_m * perimeter_m))
            compactness = min(max(compactness, 0.001), 1.0)

            # 农机作业适宜度等级评价
            if compactness >= 0.35 and p_info["area_mu"] >= 15.0:
                machinery_suitability = "优 (集中连片优质适机区)"
            elif compactness >= 0.20 or p_info["area_mu"] >= 5.0:
                machinery_suitability = "良 (标准规整农机作业区)"
            else:
                machinery_suitability = "中/碎 (建议平整并块优化)"

            # 中心坐标
            all_xs = [p[0] for p in pts_2d]
            all_ys = [p[1] for p in pts_2d]
            center_lon = float(np.mean(all_xs))
            center_lat = float(np.mean(all_ys))

            # 闭合多边形首尾点
            if pts_2d[0] != pts_2d[-1]:
                pts_2d.append(pts_2d[0])

            polygon_coords = [[round(float(c[0]), 6), round(float(c[1]), 6)] for c in pts_2d]

            prop = {
                "parcel_id": p_info["parcel_id"],
                "crop_code": p_info["dominant_crop_code"],
                "crop_name": p_info["crop_name"],
                "crop_purity": p_info["crop_purity"],
                "area_mu": p_info["area_mu"],
                "area_ha": p_info["area_ha"],
                "area_m2": p_info["area_m2"],
                "perimeter_m": round(perimeter_m, 1),
                "compactness": round(compactness, 3),
                "machinery_suitability": machinery_suitability,
                "center_lon": round(center_lon, 6),
                "center_lat": round(center_lat, 6)
            }

            features.append({
                "type": "Feature",
                "properties": prop,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon_coords]
                }
            })

            records.append(prop)

        # 写入标准 GeoJSON
        geojson_data = {
            "type": "FeatureCollection",
            "name": "from_glc10_parcels",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}
            },
            "features": features
        }

        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)

        # 写入属性表 CSV
        df = pd.DataFrame(records)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        # 生成农情类别汇总台账
        if not df.empty:
            summary_df = df.groupby(["crop_code", "crop_name"]).agg(
                parcel_count=("parcel_id", "count"),
                total_area_mu=("area_mu", "sum"),
                total_area_ha=("area_ha", "sum"),
                mean_area_mu=("area_mu", "mean"),
                mean_compactness=("compactness", "mean"),
                mean_purity=("crop_purity", "mean")
            ).reset_index()
            summary_df["area_share_pct"] = (summary_df["total_area_mu"] / summary_df["total_area_mu"].sum() * 100.0).round(2)
            summary_df = summary_df.round(2)
            summary_df.to_csv(summary_csv_path, index=False, encoding="utf-8-sig")
        else:
            summary_df = pd.DataFrame()

        return geojson_path, csv_path, summary_csv_path
