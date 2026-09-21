"""
FROM-GLC10 专用纯前端数字农情交互式 WebGIS 卫星地图生成模块。
生成单文件 HTML，内嵌 Leaflet 引擎与 GeoJSON 矢量图层。
功能特性：
1. 动态自适应分类：从 GeoJSON 动态提取所有农情类别并生成独立复选框（勾选显示/隐藏）
2. 全选 / 全不选快捷操作，实时动态统计当前勾选分类的地块数与总面积
3. 默认采用 Esri World Imagery 真实高分辨率遥感卫星底图，支持 CartoDB 标准路网与暗色底图一键平滑切换
4. 注入 no-referrer 与 CSP 策略，彻底杜绝本地 file:// 访问下的 403 跨域封锁与浏览器沙箱告警
"""

import os
import json


class GLC10WebGISBuilder:
    def __init__(self, config: dict = None):
        self.config = config or {}

    def build_map(self, geojson_path: str, output_html_path: str) -> str:
        """读取 GeoJSON 并生成自包含交互式数字农情驾驶舱 HTML 地图。"""
        if not os.path.exists(geojson_path):
            return ""

        with open(geojson_path, "r", encoding="utf-8") as f:
            geojson_content = f.read()

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src * 'unsafe-inline' 'unsafe-eval' data: blob:;">
  <title>🌾 10米 FROM-GLC10 农业地块数字监测驾驶舱</title>
  
  <!-- 引入高稳定性 Leaflet 库（支持 file:// 协议本地渲染） -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

  <style>
    body, html {{ margin: 0; padding: 0; height: 100%; width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0f172a; }}
    #map {{ height: 100%; width: 100%; background: #1e293b; }}
    
    .dashboard-panel {{
      position: absolute; top: 16px; left: 16px; z-index: 1000;
      background: rgba(255, 255, 255, 0.96); padding: 18px 20px;
      border-radius: 12px; box-shadow: 0 10px 28px rgba(0,0,0,0.22);
      width: 330px; max-width: calc(100vw - 40px); backdrop-filter: blur(10px); border: 1px solid #e2e8f0;
      max-height: calc(100vh - 40px); display: flex; flex-direction: column; box-sizing: border-box;
    }}
    .dashboard-title {{ font-size: 16px; font-weight: 800; color: #1e3a8a; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; }}
    .badge-10m {{ background: #0284c7; color: #fff; font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: bold; }}
    .stat-row {{ display: flex; justify-content: space-between; font-size: 13px; margin: 5px 0; color: #475569; }}
    .stat-val {{ font-weight: 700; color: #0f172a; }}
    
    .filter-header {{
      display: flex; justify-content: space-between; align-items: center; margin-top: 10px; margin-bottom: 6px;
      font-size: 12px; font-weight: 700; color: #334155; border-top: 1px solid #e2e8f0; padding-top: 8px;
    }}
    .filter-actions {{ display: flex; gap: 4px; }}
    .btn-mini {{
      background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px 7px;
      font-size: 11px; font-weight: 600; color: #475569; cursor: pointer; transition: all 0.15s;
    }}
    .btn-mini:hover {{ background: #e2e8f0; color: #0f172a; }}
    
    .checkbox-list {{
      overflow-y: auto; max-height: 200px; padding-right: 2px; margin-bottom: 6px;
    }}
    .crop-check-item {{
      display: flex; align-items: center; padding: 6px 8px; border-radius: 6px;
      margin-bottom: 4px; cursor: pointer; transition: background 0.12s; user-select: none;
      background: #f8fafc; border: 1px solid #f1f5f9;
    }}
    .crop-check-item:hover {{ background: #f1f5f9; border-color: #e2e8f0; }}
    .crop-check-item input[type="checkbox"] {{
      margin: 0 8px 0 0; cursor: pointer; width: 15px; height: 15px; accent-color: #1e40af;
    }}
    .crop-color-indicator {{
      width: 12px; height: 12px; border-radius: 3px; margin-right: 8px; flex-shrink: 0;
    }}
    .crop-name-label {{
      flex: 1; font-size: 12.5px; font-weight: 600; color: #1e293b;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .crop-meta-badge {{
      font-size: 11px; color: #64748b; margin-left: 6px; flex-shrink: 0; font-weight: 500;
    }}

    .basemap-switcher {{
      display: flex; gap: 4px; margin-top: 8px; background: #e2e8f0; padding: 3px; border-radius: 6px;
    }}
    .base-btn {{
      flex: 1; border: none; background: transparent; padding: 4px 6px; font-size: 11px;
      font-weight: 600; color: #475569; border-radius: 4px; cursor: pointer; text-align: center;
    }}
    .base-btn.active {{ background: #1e40af; color: #fff; }}

    .btn-fit {{
      margin-top: 8px; width: 100%; border: 1px solid #cbd5e1; background: #ffffff;
      padding: 6px; border-radius: 6px; font-size: 12px; font-weight: 700; color: #1e3a8a;
      cursor: pointer; transition: background 0.15s; text-align: center;
    }}
    .btn-fit:hover {{ background: #f8fafc; border-color: #94a3b8; }}
  </style>
</head>
<body>
  <div id="map"></div>

  <div class="dashboard-panel">
    <div class="dashboard-title">
      <span>🌾 农情空间矢量驾驶舱</span>
      <span class="badge-10m">10m 高精</span>
    </div>
    <div style="font-size: 11px; color: #64748b; margin-bottom: 6px;">数据源：清华大学 FROM-GLC10 (Science Bulletin)</div>

    <div class="stat-row"><span>当前可见地块:</span><span class="stat-val" id="total-parcels">-</span></div>
    <div class="stat-row"><span>当前耕地总面积:</span><span class="stat-val" id="total-area">-</span></div>

    <div class="filter-header">
      <span>农作物分类图层控制：</span>
      <div class="filter-actions">
        <button class="btn-mini" onclick="setAllCrops(true)">全选</button>
        <button class="btn-mini" onclick="setAllCrops(false)">清空</button>
      </div>
    </div>

    <!-- 动态复选框容器 -->
    <div class="checkbox-list" id="crop-checkbox-list">
      <!-- 由 JavaScript 根据 GeoJSON 数据动态填充 -->
    </div>

    <div class="basemap-switcher">
      <button class="base-btn active" id="btn-sat" onclick="switchBase('sat')">🛰️ 卫星底图</button>
      <button class="base-btn" id="btn-vec" onclick="switchBase('vec')">🗺️ 标准路网</button>
      <button class="base-btn" id="btn-dark" onclick="switchBase('dark')">🌙 科技暗色</button>
    </div>

    <button class="btn-fit" onclick="fitVisibleBounds()">🎯 重新聚焦地块视野</button>
  </div>

  <script>
    // 嵌入的轻量化 GeoJSON 矢量数据
    const geojsonData = {geojson_content};
    const totalParcelsCount = geojsonData.features ? geojsonData.features.length : 0;

    // 初始化 Leaflet 地图
    const map = L.map('map', {{
      center: [16.5, -13.0],
      zoom: 10,
      zoomControl: true
    }});

    // 采用稳定无跨域限制的高可用全球图层
    // 1. Esri World Imagery (真实高分辨率高空卫星影像)
    const layerSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      maxZoom: 18,
      crossOrigin: true,
      referrerPolicy: 'no-referrer',
      attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics'
    }});

    // 2. CartoDB Voyager (清爽现代矢量底图)
    const layerVec = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      subdomains: 'abcd',
      maxZoom: 19,
      crossOrigin: true,
      referrerPolicy: 'no-referrer',
      attribution: '&copy; CartoDB, OpenStreetMap'
    }});

    // 3. CartoDB Dark Matter (暗色夜景)
    const layerDark = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      subdomains: 'abcd',
      maxZoom: 19,
      crossOrigin: true,
      referrerPolicy: 'no-referrer',
      attribution: '&copy; CartoDB'
    }});

    // 默认加载卫星遥感底图
    layerSat.addTo(map);
    let currentBase = layerSat;

    function switchBase(type) {{
      map.removeLayer(currentBase);
      document.querySelectorAll('.base-btn').forEach(btn => btn.classList.remove('active'));
      if (type === 'sat') {{
        layerSat.addTo(map);
        currentBase = layerSat;
        document.getElementById('btn-sat').classList.add('active');
      }} else if (type === 'vec') {{
        layerVec.addTo(map);
        currentBase = layerVec;
        document.getElementById('btn-vec').classList.add('active');
      }} else if (type === 'dark') {{
        layerDark.addTo(map);
        currentBase = layerDark;
        document.getElementById('btn-dark').classList.add('active');
      }}
      if (geoLayer) geoLayer.bringToFront();
    }}

    function getColor(code) {{
      switch(parseInt(code)) {{
        case 10: return '#16a34a'; // 耕地 - 翠绿
        case 20: return '#065f46'; // 森林 - 深绿
        case 30: return '#84cc16'; // 草地 - 浅绿
        case 40: return '#65a30d'; // 灌木丛 - 橄榄
        case 50: return '#0ea5e9'; // 湿地 - 青色
        case 60: return '#1d4ed8'; // 水体 - 深蓝
        case 80: return '#64748b'; // 建筑 - 灰色
        case 90: return '#d97706'; // 裸地 - 棕褐
        default: return '#059669';
      }}
    }}

    // 1. 动态扫描 GeoJSON 数据中实际存在的农作物类别与面积统计
    const cropStats = {{}};
    if (geojsonData.features) {{
      geojsonData.features.forEach(f => {{
        const p = f.properties || {{}};
        const code = parseInt(p.crop_code) || 10;
        const name = p.crop_name || ('农作物(代码' + code + ')');
        const mu = parseFloat(p.area_mu) || 0;
        if (!cropStats[code]) {{
          cropStats[code] = {{ code: code, name: name, count: 0, totalMu: 0 }};
        }}
        cropStats[code].count += 1;
        cropStats[code].totalMu += mu;
      }});
    }}

    // 活跃勾选的类别代码集合
    const activeCodes = new Set(Object.keys(cropStats).map(c => parseInt(c)));

    // 2. 动态生成多分类勾选复选框列表
    const checkListContainer = document.getElementById('crop-checkbox-list');
    checkListContainer.innerHTML = '';

    const sortedCodes = Object.keys(cropStats).sort((a, b) => parseInt(a) - parseInt(b));
    if (sortedCodes.length === 0) {{
      checkListContainer.innerHTML = '<div style="font-size:12px;color:#94a3b8;padding:8px 4px;">暂无可显示农作物图层</div>';
    }} else {{
      sortedCodes.forEach(codeStr => {{
        const code = parseInt(codeStr);
        const item = cropStats[code];
        const color = getColor(code);
        const label = document.createElement('label');
        label.className = 'crop-check-item';
        label.title = `点击勾选/取消显示：${{item.name}}`;
        label.innerHTML = `
          <input type="checkbox" id="chk-crop-${{code}}" value="${{code}}" checked onchange="toggleCropCategory(${{code}}, this.checked)">
          <span class="crop-color-indicator" style="background:${{color}}"></span>
          <span class="crop-name-label">${{item.name}}</span>
          <span class="crop-meta-badge">${{item.count}}块 · ${{item.totalMu.toLocaleString(undefined, {{maximumFractionDigits:1}})}}亩</span>
        `;
        checkListContainer.appendChild(label);
      }});
    }}

    let geoLayer = null;

    function renderLayer() {{
      if (geoLayer) map.removeLayer(geoLayer);
      let visibleCount = 0;
      let visibleMu = 0;

      geoLayer = L.geoJSON(geojsonData, {{
        filter: function(feat) {{
          const code = parseInt(feat.properties.crop_code) || 10;
          return activeCodes.has(code);
        }},
        style: function(feat) {{
          const col = getColor(feat.properties.crop_code);
          return {{
            color: '#ffffff',
            weight: 1.5,
            fillColor: col,
            fillOpacity: 0.65
          }};
        }},
        onEachFeature: function(feat, layer) {{
          visibleCount++;
          visibleMu += parseFloat(feat.properties.area_mu) || 0;
          const p = feat.properties;
          let suitColor = '#16a34a';
          if ((p.machinery_suitability || '').indexOf('良') !== -1) suitColor = '#0284c7';
          else if ((p.machinery_suitability || '').indexOf('中') !== -1) suitColor = '#d97706';
          else if ((p.machinery_suitability || '').indexOf('异形') !== -1 || (p.machinery_suitability || '').indexOf('碎') !== -1) suitColor = '#dc2626';

          const content = `
            <div style="font-size:13px; line-height:1.6; min-width:210px;">
              <div style="font-size:14px; font-weight:800; color:#1e3a8a; margin-bottom:5px; border-bottom:1px solid #e2e8f0; padding-bottom:3px;">
                📍 ${{p.parcel_id}}
              </div>
              <b>作物类别:</b> ${{p.crop_name}} (代码 ${{p.crop_code}})<br/>
              <b>物理面积:</b> <span style="color:#16a34a; font-weight:bold;">${{Number(p.area_mu).toLocaleString()}} 亩</span> (${{p.area_ha}} ha)<br/>
              <b>地块周长:</b> ${{Number(p.perimeter_m).toLocaleString()}} 米<br/>
              <b>形状紧凑度:</b> ${{p.compactness}}<br/>
              <b>适机评级:</b> <span style="color:${{suitColor}}; font-weight:700; background:#f8fafc; padding:1px 6px; border-radius:4px; border:1px solid #e2e8f0;">${{p.machinery_suitability}}</span><br/>
              <b>中心经纬度:</b> [${{p.center_lon}}°, ${{p.center_lat}}°]
            </div>
          `;
          layer.bindPopup(content);
          
          layer.on('mouseover', function() {{
            this.setStyle({{ weight: 3.0, color: '#fef08a', fillOpacity: 0.85 }});
          }});
          layer.on('mouseout', function() {{
            geoLayer.resetStyle(this);
          }});
        }}
      }}).addTo(map);

      document.getElementById('total-parcels').innerText = `${{visibleCount}} 块 (共 ${{totalParcelsCount}} 块)`;
      document.getElementById('total-area').innerText = `${{visibleMu.toLocaleString(undefined, {{maximumFractionDigits:1}})}} 亩`;
    }}

    function toggleCropCategory(code, isChecked) {{
      if (isChecked) {{
        activeCodes.add(parseInt(code));
      }} else {{
        activeCodes.delete(parseInt(code));
      }}
      renderLayer();
    }}

    function setAllCrops(state) {{
      document.querySelectorAll('.crop-check-item input[type="checkbox"]').forEach(chk => {{
        chk.checked = state;
        const c = parseInt(chk.value);
        if (state) activeCodes.add(c);
        else activeCodes.delete(c);
      }});
      renderLayer();
    }}

    function fitVisibleBounds() {{
      if (geoLayer && geoLayer.getBounds().isValid()) {{
        map.fitBounds(geoLayer.getBounds(), {{ padding: [30, 30] }});
      }}
    }}

    // 初始渲染并自动聚焦视野
    renderLayer();
    fitVisibleBounds();
  </script>
</body>
</html>
"""
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_html_path
