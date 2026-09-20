"""
FROM-GLC10 专用 10 米农业地块形态学切分与田埂分割模块。
对应《联合国农业统计遥感手册》第 8 章。
实现功能：
1. 相邻不同农作物交界处零拷贝差分梯度切断
2. 10 米高精度形态学田埂开运算（Opening）与桥接腐蚀
3. 农田内部车辙阴影空洞闭合与细小碎斑噪声滤除
4. 独立连通域农田地块标记与多数投票类别裁定
"""

import numpy as np
from scipy import ndimage


class GLC10ParcelSegmenter:
    def __init__(self, config: dict = None):
        self.config = config or {}
        seg_cfg = self.config.get("segmentation", {})
        self.apply_erosion = seg_cfg.get("apply_boundary_erosion", True)
        self.kernel_size = seg_cfg.get("erosion_kernel_size", 3)
        self.cut_cross_crop = seg_cfg.get("cut_cross_crop_boundaries", True)
        self.fill_holes = seg_cfg.get("fill_internal_holes", True)
        self.min_area_m2 = seg_cfg.get("min_parcel_area_m2", 200.0)
        self.max_area_m2 = seg_cfg.get("max_parcel_area_m2", 500000.0)
        self.max_export_parcels = seg_cfg.get("max_export_parcels", 800)
        self.res_meters = self.config.get("spatial", {}).get("nominal_resolution_meters", 10.0)
        self.pixel_area_m2 = self.res_meters * self.res_meters  # 100 m²
        self.target_crop_codes = self.config.get("glc10_classes", {}).get("target_crop_codes", {})

    def segment_parcels(self, crop_mask: np.ndarray) -> tuple:
        """
        对 10 米农作物图层执行田埂形态学分割与地块斑块提取。
        参数:
            crop_mask (np.ndarray): 农作物分类代码矩阵 (0=非农, 11=水稻, 12=大棚, 13=旱作等)
        返回:
            parcel_id_mask (np.ndarray): 独立地块编号矩阵 (0=田埂/非农, 1..N=独立地块)
            parcel_list (list): 各地块属性字典清单
        """
        rows, cols = crop_mask.shape
        cropland_binary = (crop_mask > 0).astype(np.uint8)

        # 1. 相邻不同农作物之间的交界处切片差分梯度断开
        if self.cut_cross_crop and rows > 1 and cols > 1:
            diff_v = (crop_mask[:-1, :] > 0) & (crop_mask[1:, :] > 0) & (crop_mask[:-1, :] != crop_mask[1:, :])
            diff_h = (crop_mask[:, :-1] > 0) & (crop_mask[:, 1:] > 0) & (crop_mask[:, :-1] != crop_mask[:, 1:])

            cropland_binary[:-1, :][diff_v] = 0
            cropland_binary[1:, :][diff_v] = 0
            cropland_binary[:, :-1][diff_h] = 0
            cropland_binary[:, 1:][diff_h] = 0

        # 2. 10 米专属形态学开运算 (Opening = 腐蚀+膨胀)，切断 1~2 像素宽度的细窄机耕道与田埂
        if self.apply_erosion:
            k = max(3, self.kernel_size if self.kernel_size % 2 == 1 else self.kernel_size + 1)
            structure = np.ones((k, k), dtype=np.uint8)
            cleaned = ndimage.binary_opening(cropland_binary, structure=structure).astype(np.uint8)
        else:
            cleaned = cropland_binary

        # 3. 闭合地块内部微小空洞（如阴影或孤立失测像元）
        if self.fill_holes:
            cleaned = ndimage.binary_fill_holes(cleaned).astype(np.uint8)

        # 4. 8-连通域标记独立农田斑块
        structure_conn = ndimage.generate_binary_structure(2, 2)
        labeled_array, num_features = ndimage.label(cleaned, structure=structure_conn)

        if num_features == 0:
            return np.zeros((rows, cols), dtype=np.int32), []

        # 5. 统计每个斑块大小并进行合法面积筛选
        counts = np.bincount(labeled_array.ravel())
        component_sizes = counts[1:num_features + 1]
        areas_m2 = component_sizes * self.pixel_area_m2

        # 面积阈值区间筛选 [min_area_m2, max_area_m2]
        valid_comp_indices = np.where((areas_m2 >= self.min_area_m2) & (areas_m2 <= self.max_area_m2))[0] + 1

        if len(valid_comp_indices) == 0:
            # 宽容兜底：若全图斑块较大，放宽上限
            valid_comp_indices = np.where(areas_m2 >= self.min_area_m2)[0] + 1

        # 按地块面积降序排列，优选主力核心地块
        sorted_order = np.argsort(-areas_m2[valid_comp_indices - 1])
        sorted_valid = valid_comp_indices[sorted_order]

        if len(sorted_valid) > self.max_export_parcels:
            selected_comps = sorted_valid[:self.max_export_parcels].tolist()
        else:
            selected_comps = sorted_valid.tolist()

        # 6. 生成新的地块编号掩膜与提取地块属性
        parcel_id_mask = np.zeros((rows, cols), dtype=np.int32)
        slices = ndimage.find_objects(labeled_array)
        parcel_list = []

        for new_id, comp_id in enumerate(selected_comps, start=1):
            sl = slices[comp_id - 1]
            if sl is None:
                continue

            sub_labeled = labeled_array[sl]
            comp_mask_local = (sub_labeled == comp_id)

            # 写入全局地块 ID
            parcel_id_mask[sl][comp_mask_local] = new_id

            # 多数投票裁定地块主导农作物类别
            sub_crops = crop_mask[sl][comp_mask_local]
            crop_codes, crop_counts = np.unique(sub_crops[sub_crops > 0], return_counts=True)

            if len(crop_codes) > 0:
                dominant_code = int(crop_codes[np.argmax(crop_counts)])
                purity = float(np.max(crop_counts) / len(sub_crops))
            else:
                dominant_code = 10
                purity = 1.0

            crop_name = self.target_crop_codes.get(dominant_code, f"农作物(代码{dominant_code})")
            area_m2 = float(np.sum(comp_mask_local)) * self.pixel_area_m2
            area_mu = area_m2 / (2000.0 / 3.0)
            area_ha = area_m2 / 10000.0

            parcel_list.append({
                "parcel_id": f"GLC10_P{new_id:04d}",
                "int_id": new_id,
                "dominant_crop_code": dominant_code,
                "crop_name": crop_name,
                "crop_purity": round(purity, 3),
                "pixel_count": int(np.sum(comp_mask_local)),
                "area_m2": round(area_m2, 1),
                "area_mu": round(area_mu, 2),
                "area_ha": round(area_ha, 2),
                "bbox_slice": sl
            })

        return parcel_id_mask, parcel_list
