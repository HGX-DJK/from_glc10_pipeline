"""
环境兼容性与 PROJ/GDAL 冲突自动修复模块。
彻底解决 Windows 下安装 PostgreSQL/PostGIS 导致的旧版 proj.db 冲突问题：
'rasterio.errors.CRSError: The EPSG code is unknown. PROJ: proj_create_from_database: ... contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is expected.'
"""

import os
import sys

def sanitize_proj_gdal_env():
    """
    1. 动态查找 Python 当前环境中 rasterio 自带的 proj_data 目录 (包含版本匹配的 proj.db)。
    2. 强制覆盖系统环境变量 PROJ_LIB 与 PROJ_DATA，彻底免疫 PostgreSQL/PostGIS 的老旧版本冲突。
    3. 清理过期的 GDAL_DATA 变量。
    """
    # 查找 rasterio 自带的 proj_data
    target_proj_dir = None
    for p in sys.path:
        cand = os.path.join(p, "rasterio", "proj_data")
        if os.path.exists(os.path.join(cand, "proj.db")):
            target_proj_dir = cand
            break

    if target_proj_dir:
        os.environ["PROJ_LIB"] = target_proj_dir
        os.environ["PROJ_DATA"] = target_proj_dir
    else:
        # 未定位到 rasterio 自带目录时，清理第三方冲突目录
        for var in ["PROJ_LIB", "PROJ_DATA"]:
            val = os.environ.get(var, "")
            if "postgresql" in val.lower() or "postgis" in val.lower() or not os.path.exists(val):
                os.environ.pop(var, None)

    # 清理外部 GDAL_DATA
    gdal_val = os.environ.get("GDAL_DATA", "")
    if "postgresql" in gdal_val.lower() or "postgis" in gdal_val.lower():
        os.environ.pop("GDAL_DATA", None)

    # 尝试设置 rasterio 自带 gdal_data
    for p in sys.path:
        cand_gdal = os.path.join(p, "rasterio", "gdal_data")
        if os.path.exists(cand_gdal):
            os.environ["GDAL_DATA"] = cand_gdal
            break

# 模块载入时立即执行
sanitize_proj_gdal_env()

# 确保在 Windows 控制台下正常输出 Unicode/Emoji 字符
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
