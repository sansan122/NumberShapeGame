"""
《数与形》地图可视化
------------------------------------------------------------
作用：读取 out/map.json，生成一个可以直接双击打开的网页。

怎么用：
    C:\\Users\\sanji\\.workbuddy\\binaries\\python\\envs\\naf\\Scripts\\python.exe tools/render_map.py

生成 out/map.html，双击它就能在浏览器里看到地图。
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_JSON = ROOT / "out" / "map.json"
HTML_OUT = ROOT / "out" / "map.html"

# 节点类型的颜色（浅色底 + 深色边）
NODE_COLORS = {
    "battle":   ("#E6F1FB", "#185FA5"),
    "elite":    ("#FAEEDA", "#BA7517"),
    "rest":     ("#EAF3DE", "#3B6D11"),
    "shop":     ("#EEEDFE", "#534AB7"),
    "event":    ("#FBEAF0", "#993556"),
    "treasure": ("#FAECE7", "#993C1D"),
    "boss":     ("#FBEAF0", "#72243E"),
}


def build_floor_svg(floor, row_h=46, col_gap=86, pad_x=46, pad_y=30):
    """把一层的节点和边画成 SVG。"""
    nodes = floor["nodes"]
    edges = floor["edges"]
    rows = max(n["row"] for n in nodes) + 1

    w = 620
    h = pad_y * 2 + rows * row_h

    # 节点坐标：x 由 node["x"] 比例决定，y 由行号决定
    # 注意：塔从下往上爬，所以 row 0 应在最下面
    pos = {}
    for n in nodes:
        x = pad_x + n["x"] * (w - pad_x * 2)
        y = h - pad_y - n["row"] * row_h
        pos[n["id"]] = (x, y)

    parts = []

    # ---- 先画边 ----
    for e in edges:
        x1, y1 = pos[e["from"]]
        x2, y2 = pos[e["to"]]
        if e["cost"]:
            # 带代价的边：用醒目颜色 + 虚线
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#D85A30" stroke-width="2" stroke-dasharray="5 3" '
                f'opacity="0.85"/>'
            )
        else:
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'stroke="#B4B2A9" stroke-width="1" opacity="0.7"/>'
            )

    # ---- 再画节点（覆盖在边上）----
    for n in nodes:
        x, y = pos[n["id"]]
        fill, stroke = NODE_COLORS.get(n["type"], ("#F1EFE8", "#5F5E5A"))
        r = 15 if n["type"] == "boss" else 12
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.6"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="11" fill="{stroke}">'
            f'{n["icon"]}</text>'
        )

    # ---- 带代价的边加文字标注 ----
    for e in edges:
        if not e["cost"]:
            continue
        x1, y1 = pos[e["from"]]
        x2, y2 = pos[e["to"]]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        parts.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="9" fill="#993C1D" '
            f'paint-order="stroke" stroke="#FFFFFF" stroke-width="3">'
            f'{e["cost"]["name"]}</text>'
        )

    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" '
        f'style="max-width:{w}px;display:block">' + "".join(parts) + "</svg>"
    )


def build_html(data):
    """组装整页 HTML。"""
    floors_html = []

    for fl in data["floors"]:
        s = fl["stats"]
        svg = build_floor_svg(fl)

        # 该层用到的代价标签汇总
        costs = {}
        for e in fl["edges"]:
            if e["cost"]:
                costs[e["cost"]["name"]] = e["cost"]

        cost_chips = "".join(
            f'<span class="chip" title="{c["desc"]}｜{c["math_note"]}">'
            f'{c["name"]}</span>'
            for c in costs.values()
        )

        floors_html.append(f"""
    <section class="floor">
      <div class="floor-head" style="border-left-color:{fl['theme_color']}">
        <h2>第 {fl['id']} 层　{fl['name']}</h2>
        <p class="meta">
          <span class="tag" style="background:{fl['theme_color']}22;color:{fl['theme_color']}">{fl['stage']}</span>
          <span class="tag" style="background:{fl['theme_color']}22;color:{fl['theme_color']}">{fl['grade']}</span>
          <span class="boss">层主：{fl['boss']}（{fl['boss_hp']} 血）</span>
        </p>
        <p class="desc">{fl['desc']}</p>
      </div>

      <div class="stats">
        <div class="stat"><b>{s['node_count']}</b><span>节点</span></div>
        <div class="stat"><b>{s['battle_count']}</b><span>普通战斗</span></div>
        <div class="stat"><b>{s['elite_count']}</b><span>精英</span></div>
        <div class="stat"><b>{s['rest_count']}</b><span>休整点</span></div>
        <div class="stat"><b>{s['edge_count']}</b><span>连边</span></div>
        <div class="stat hl"><b>{s['cost_edge_count']}</b><span>带代价</span></div>
      </div>

      <div class="costs">{cost_chips}</div>
      <div class="canvas">{svg}</div>
    </section>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>《数与形》地图预览</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px 64px;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #FAFAF8; color: #2C2C2A; line-height: 1.6;
  }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  header {{ margin-bottom: 36px; }}
  header h1 {{ font-size: 22px; font-weight: 500; margin: 0 0 6px; }}
  header p {{ margin: 0; font-size: 13px; color: #5F5E5A; }}
  .floor {{
    background: #FFF; border: 1px solid rgba(0,0,0,0.08);
    border-radius: 14px; padding: 24px; margin-bottom: 28px;
  }}
  .floor-head {{ border-left: 3px solid #ccc; padding-left: 14px; margin-bottom: 18px; }}
  .floor-head h2 {{ font-size: 17px; font-weight: 500; margin: 0 0 8px; }}
  .meta {{ margin: 0 0 8px; font-size: 12px; }}
  .tag {{
    display: inline-block; padding: 2px 8px; border-radius: 5px;
    margin-right: 6px; font-size: 11px;
  }}
  .boss {{ color: #5F5E5A; }}
  .desc {{ margin: 0; font-size: 13px; color: #5F5E5A; }}
  .stats {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
  .stat {{
    background: #F1EFE8; border-radius: 8px; padding: 8px 14px;
    text-align: center; min-width: 72px;
  }}
  .stat b {{ display: block; font-size: 17px; font-weight: 500; }}
  .stat span {{ font-size: 11px; color: #5F5E5A; }}
  .stat.hl {{ background: #FAECE7; }}
  .stat.hl b {{ color: #993C1D; }}
  .costs {{ margin-bottom: 12px; min-height: 22px; }}
  .chip {{
    display: inline-block; background: #FAECE7; color: #993C1D;
    border-radius: 5px; padding: 2px 9px; font-size: 11px; margin: 0 6px 6px 0;
    cursor: help;
  }}
  .canvas {{ background: #FCFCFA; border-radius: 10px; padding: 8px; }}
  .legend {{
    display: flex; gap: 16px; flex-wrap: wrap;
    font-size: 12px; color: #5F5E5A; margin-top: 10px;
  }}
  .legend i {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 5px; vertical-align: middle;
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>《数与形》地图预览 · {data['tower_name']}</h1>
    <p>随机种子 {data['seed']}　·　橙色虚线代表带「路线代价」的路径，鼠标悬停可看说明</p>
  </header>

  {''.join(floors_html)}

  <div class="legend">
    <span><i style="background:#E6F1FB;border:1px solid #185FA5"></i>普通战斗</span>
    <span><i style="background:#FAEEDA;border:1px solid #BA7517"></i>精英</span>
    <span><i style="background:#EAF3DE;border:1px solid #3B6D11"></i>休整点</span>
    <span><i style="background:#EEEDFE;border:1px solid #534AB7"></i>商店</span>
    <span><i style="background:#FBEAF0;border:1px solid #993556"></i>事件</span>
    <span><i style="background:#FAECE7;border:1px solid #993C1D"></i>宝箱</span>
  </div>
</div>
</body>
</html>"""


def main():
    if not MAP_JSON.exists():
        print(f"[错误] 找不到 {MAP_JSON}")
        print("请先运行：python tools/build_map.py")
        return

    data = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    HTML_OUT.write_text(build_html(data), encoding="utf-8")
    print(f"已生成预览网页：{HTML_OUT}")
    print("双击这个文件就能在浏览器里打开。")


if __name__ == "__main__":
    main()
