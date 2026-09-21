"""
FROM-GLC10 农业地块提取与联合国无偏估计算法包
基于联合国粮农组织与统计司 (FAO/UNSD)《农业统计遥感手册》(UN-Handbook) 标准
"""

__version__ = "1.0.0"

# 自动处理 Windows 下 PostgreSQL/PostGIS 注入的 PROJ_LIB 冲突
try:
    from src.env_utils import sanitize_proj_gdal_env
    sanitize_proj_gdal_env()
except ImportError:
    pass

