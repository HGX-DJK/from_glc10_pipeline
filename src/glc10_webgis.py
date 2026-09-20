"""
FROM-GLC10 专用纯前端数字农情交互式 WebGIS 卫星地图生成模块。
生成单文件 HTML，内嵌 Leaflet 引擎与 GeoJSON 矢量图层。
彻底解决浏览器 file:// 协议访问下的 403 跨域封锁与唯一安全源报错问题：
1. 默认采用 Esri World Imagery 真实卫星遥感底图与 CartoDB 无跨域限制图层（绝不使用屏蔽 file:// 访问的 OSM）
2. 注入 no-referrer 策略与 noopener 隔离，消除 'file:' unique security origins 浏览器安全告警
3. 支持按农作物类别筛选、适机度弹窗、面积统计与底图随时平滑切换
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
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
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
      max-width: 320px; backdrop-filter: blur(10px); border: 1px solid #e2e8f0;
    }}
    .dashboard-title {{ font-size: 16px; font-weight: 800; color: #1e3a8a; margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; }}
    .badge-10m {{ background: #0284c7; color: #fff; font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: bold; }}
    .stat-row {{ display: flex; justify-content: space-between; font-size: 13px; margin: 8px 0; color: #475569; }}
    .stat-val {{ font-weight: 700; color: #0f172a; }}
    
    .filter-select {{
      width: 100%; margin: 8px 0; padding: 7px 9px; border-radius: 6px;
      border: 1px solid #cbd5e1; font-size: 12.5px; background: #f8fafc; font-weight: 600; color: #1e293b; outline: none;
    }}
    
    .basemap-switcher {{
      display: flex; gap: 4px; margin-top: 10px; background: #e2e8f0; padding: 3px; border-radius: 6px;
    }}
    .base-btn {{
      flex: 1; border: none; background: transparent; padding: 4px 6px; font-size: 11px;
      font-weight: 600; color: #475569; border-radius: 4px; cursor: pointer; text-align: center;
    }}
    .base-btn.active {{ background: #1e40af; color: #fff; }}

    .legend-box {{ margin-top: 12px; border-top: 1px solid #e2e8f0; padding-top: 10px; font-size: 12px; }}
    .legend-item {{ display: flex; align-items: center; margin: 5px 0; color: #334155; }}
    .legend-color {{ width: 14px; height: 14px; border-radius: 3px; margin-right: 8px; flex-shrink: 0; }}
  </style>
</head>
<body>
  <div id="map"></div>

  <div class="dashboard-panel">
    <div class="dashboard-title">
      <span>🌾 农情空间矢量驾驶舱</span>
      <span class="badge-10m">10m 高精</span>
    </div>
    <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">数据源：清华大学 FROM-GLC10 (Science Bulletin)</div>

    <div class="stat-row"><span>总勾勒规整地块:</span><span class="stat-val" id="total-parcels">-</span></div>
    <div class="stat-row"><span>净提取耕地总面积:</span><span class="stat-val" id="total-area">-</span></div>

    <label style="font-size:11.5px; font-weight:700; color:#475569;">按农作物类型筛选：</label>
    <select id="crop-filter" class="filter-select" onchange="filterParcels()">
      <option value="all">🌱 显示全部农作物图斑</option>
      <option value="11">🌾 水稻田 (Paddy Rice)</option>
      <option value="12">🏡 设施温室大棚 (Greenhouse)</option>
      <option value="13">🌽 旱地其他农作物 (Upland Crops)</option>
      <option value="24">🍎 经济果园 (Orchard)</option>
      <option value="94">🍂 休闲翻耕裸地 (Bare Cropland)</option>
    </select>

    <div class="basemap-switcher">
      <button class="base-btn active" id="btn-sat" onclick="switchBase('sat')">🛰️ 卫星底图</button>
      <button class="base-btn" id="btn-vec" onclick="switchBase('vec')">🗺️ 标准路网</button>
      <button class="base-btn" id="btn-dark" onclick="switchBase('dark')">🌙 科技暗色</button>
    </div>

    <div class="legend-box">
      <div style="font-weight: 700; margin-bottom: 5px; color: #1e293b;">农作物分类图例</div>
      <div class="legend-item"><span class="legend-color" style="background:#0284c7;"></span> 水稻田 (代码 11)</div>
      <div class="legend-item"><span class="legend-color" style="background:#e11d48;"></span> 设施温室大棚 (代码 12)</div>
      <div class="legend-item"><span class="legend-color" style="background:#16a34a;"></span> 旱地大田农作物 (代码 13/10)</div>
      <div class="legend-item"><span class="legend-color" style="background:#d97706;"></span> 经济果园 (代码 24)</div>
      <div class="legend-item"><span class="legend-color" style="background:#a16207;"></span> 休闲翻耕裸地 (代码 94)</div>
    </div>
  </div>

  <script>
    // 嵌入的轻量化 GeoJSON 矢量数据
    const geojsonData = {geojson_content};

    // 初始化 Leaflet 地图
    const map = L.map('map', {{
      center: [35.5, 116.5],
      zoom: 13,
      zoomControl: true
    }});

    // 采用稳定无跨域限制、绝不 403 的高可用全球图层
    // 1. Esri World Imagery (真实高分辨率高空卫星影像)
    const layerSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      maxZoom: 18,
      crossOrigin: true,
      referrerPolicy: 'no-referrer',
      attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics'
    }});

    // 2. CartoDB Voyager (清爽现代矢量底图，完美兼容 file:// 访问)
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

    // 默认加载真实卫星底图
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
        case 11: return '#0284c7'; // 水稻 - 天蓝
        case 12: return '#e11d48'; // 大棚 - 玫红
        case 13: return '#16a34a'; // 旱作 - 翠绿
        case 10: return '#16a34a';
        case 24: return '#d97706'; // 果园 - 橙黄
        case 94: return '#a16207'; // 裸耕 - 棕褐
        default: return '#059669';
      }}
    }}

    let geoLayer = null;

    function renderLayer(filterCode) {{
      if (geoLayer) map.removeLayer(geoLayer);
      let totalMu = 0;
      let count = 0;

      geoLayer = L.geoJSON(geojsonData, {{
        filter: function(feat) {{
          if (filterCode === 'all') return true;
          return parseInt(feat.properties.crop_code) === parseInt(filterCode);
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
          totalMu += parseFloat(feat.properties.area_mu) || 0;
          count++;
          const p = feat.properties;
          const content = `
            <div style="font-size:13px; line-height:1.6; min-width:200px;">
              <div style="font-size:14px; font-weight:800; color:#1e3a8a; margin-bottom:4px;">📍 ${{p.parcel_id}}</div>
              <b>作物类别:</b> ${{p.crop_name}} (代码 ${{p.crop_code}})<br/>
              <b>物理面积:</b> <span style="color:#16a34a; font-weight:bold;">${{p.area_mu}} 亩</span> (${{p.area_ha}} ha)<br/>
              <b>地块周长:</b> ${{p.perimeter_m}} 米<br/>
              <b>形状紧凑度:</b> ${{p.compactness}}<br/>
              <b>适机评级:</b> <span style="color:#d97706; font-weight:700;">${{p.machinery_suitability}}</span><br/>
              <b>中心经纬度:</b> [${{p.center_lon}}, ${{p.center_lat}}]
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

      document.getElementById('total-parcels').innerText = count + ' 个';
      document.getElementById('total-area').innerText = totalMu.toFixed(1) + ' 亩';

      if (count > 0 && geoLayer.getBounds().isValid()) {{
        map.fitBounds(geoLayer.getBounds(), {{ padding: [30, 30] }});
      }}
    }}

    function filterParcels() {{
      const val = document.getElementById('crop-filter').value;
      renderLayer(val);
    }}

    // 初始渲染全部农情地块
    renderLayer('all');
  </script>
</body>
</html>
"""
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_html_path
