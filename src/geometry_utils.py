"""
FROM-GLC10 专用地块几何拓扑追踪、抽稀与样条平滑算法模块。
纯 Python / NumPy 实现，零外部 C++ 库依赖。
"""

import numpy as np


def trace_grid_boundary(binary_mask):
    """
    针对二值像元掩膜，精确提取外边界网格多边形闭合序列（无自相交、顺时针闭合环）。
    """
    padded = np.pad(binary_mask.astype(bool), 1, mode='constant', constant_values=False)
    
    edges = {}
    rows, cols = np.where(padded)
    for r, c in zip(rows, cols):
        if not padded[r - 1, c]:
            edges.setdefault((r, c), []).append((r, c + 1))
        if not padded[r, c + 1]:
            edges.setdefault((r, c + 1), []).append((r + 1, c + 1))
        if not padded[r + 1, c]:
            edges.setdefault((r + 1, c + 1), []).append((r + 1, c))
        if not padded[r, c - 1]:
            edges.setdefault((r + 1, c), []).append((r, c))

    if not edges:
        return []

    rings = []
    remaining = {k: list(v) for k, v in edges.items()}
    max_total_steps = sum(len(v) for v in edges.values()) + 10
    total_steps = 0

    while True:
        start = None
        for k, v in remaining.items():
            if v:
                start = k
                break
        if start is None:
            break

        ring = [start]
        curr = start
        while True:
            total_steps += 1
            if total_steps > max_total_steps:
                break

            targets = remaining.get(curr, [])
            if not targets:
                break
            
            if len(targets) == 1:
                nxt = targets.pop(0)
            else:
                if len(ring) >= 2:
                    dr_in = curr[0] - ring[-2][0]
                    dc_in = curr[1] - ring[-2][1]
                else:
                    dr_in, dc_in = 0, 1
                
                best_t = None
                best_angle = -999.0
                for t in targets:
                    dr_out = t[0] - curr[0]
                    dc_out = t[1] - curr[1]
                    cross = dr_in * dc_out - dc_in * dr_out
                    dot = dr_in * dr_out + dc_in * dc_out
                    angle = np.arctan2(cross, dot)
                    if angle > best_angle:
                        best_angle = angle
                        best_t = t
                nxt = best_t
                targets.remove(nxt)

            ring.append(nxt)
            curr = nxt
            if curr == start:
                break

        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)

        if total_steps > max_total_steps:
            break

    if not rings:
        return []

    best_ring = None
    max_area = -1.0
    for ring in rings:
        area = 0.0
        for i in range(len(ring) - 1):
            area += (ring[i][1] * ring[i + 1][0] - ring[i + 1][1] * ring[i][0])
        area = abs(area) * 0.5
        if area > max_area:
            max_area = area
            best_ring = ring

    if not best_ring:
        return []

    pts = [(r - 1.0, c - 1.0) for r, c in best_ring]
    return pts


def simplify_polygon(points, tolerance: float = 0.5):
    """
    Ramer-Douglas-Peucker (RDP) 多边形拓扑抽稀。
    消除网格严格共线中间点，大幅压缩点集规模，保留宏观农田几何特征。
    """
    if len(points) <= 4:
        return points

    # 1. 消除严格共线网格点
    filtered = [points[0]]
    for i in range(1, len(points) - 1):
        p_prev = filtered[-1]
        p_curr = points[i]
        p_next = points[i + 1]
        dr1 = p_curr[0] - p_prev[0]
        dc1 = p_curr[1] - p_prev[1]
        dr2 = p_next[0] - p_curr[0]
        dc2 = p_next[1] - p_curr[1]
        cross = dr1 * dc2 - dc1 * dr2
        if abs(cross) > 1e-6:
            filtered.append(p_curr)
    filtered.append(points[-1])

    if len(filtered) <= 4:
        return filtered

    # 2. 闭合环 RDP 抽稀
    pts_arr = np.array(filtered)
    dists = np.linalg.norm(pts_arr[:-1] - pts_arr[0], axis=1)
    far_idx = int(np.argmax(dists))

    def _rdp(pts, eps):
        if len(pts) <= 2:
            return pts
        pt1 = pts[0]
        pt2 = pts[-1]
        line_vec = pt2 - pt1
        line_norm = np.linalg.norm(line_vec)
        if line_norm < 1e-6:
            d = np.linalg.norm(pts - pt1, axis=1)
        else:
            u = line_vec / line_norm
            v = pts - pt1
            proj = np.outer(np.dot(v, u), u)
            d = np.linalg.norm(v - proj, axis=1)
        idx = int(np.argmax(d))
        if d[idx] > eps:
            left = _rdp(pts[:idx + 1], eps)
            right = _rdp(pts[idx:], eps)
            return np.vstack([left[:-1], right])
        else:
            return np.vstack([pts[0], pts[-1]])

    part1 = _rdp(pts_arr[:far_idx + 1], tolerance)
    part2 = _rdp(pts_arr[far_idx:], tolerance)
    simplified = np.vstack([part1[:-1], part2])

    res = [tuple(p) for p in simplified]
    if not np.allclose(res[0], res[-1]):
        res.append(res[0])
    return res


def chaikin_smooth(points, iterations: int = 2):
    """
    Chaikin 拐角切割拓扑平滑算法，消除栅格锯齿。
    """
    if len(points) < 4 or iterations <= 0:
        return points
    
    pts = list(points)
    is_closed = np.allclose(pts[0], pts[-1])
    if is_closed:
        pts = pts[:-1]
        
    n = len(pts)
    if n < 3:
        return points

    for _ in range(iterations):
        smoothed = []
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            q_x = 0.75 * p0[0] + 0.25 * p1[0]
            q_y = 0.75 * p0[1] + 0.25 * p1[1]
            r_x = 0.25 * p0[0] + 0.75 * p1[0]
            r_y = 0.25 * p0[1] + 0.75 * p1[1]
            smoothed.append((q_x, q_y))
            smoothed.append((r_x, r_y))
        pts = smoothed
        n = len(pts)

    if is_closed:
        pts.append(pts[0])
    return pts


def haversine_distance(lon1, lat1, lon2, lat2) -> float:
    """计算地球表面两经纬度点间的大圆距离（米）。"""
    r_earth = 6371000.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0)**2
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return float(r_earth * c)
