# 세대 히스토리 브라우저 - 모든 후보의 계보/결과/게이트 증거를 한 페이지로 낸다
"""
사용: python report.py   ->  history.html 생성

세대는 지우지 않으므로 실패(INVALID)도 함께 보인다. 어떤 시도가 왜 탈락했는지가
다음 세션에 그대로 넘어간다.
"""

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generation  # noqa: E402

import workspace as ws

ROOT = ws.WS

CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#e3e3e3;--acc:#0b5;--bad:#c33;--gold:#b8860b;--card:#fafafa}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e8e8e8;--mut:#9aa;--line:#2c3038;--acc:#3d8;--bad:#f66;--gold:#e0a83a;--card:#1d2026}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem;background:var(--bg);color:var(--fg);
 font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:1.55rem;margin:0 0 .3rem}
h2{font-size:1.1rem;margin:2.2rem 0 .7rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
.sub{color:var(--mut);margin:0 0 1.6rem;font-size:.92rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:.7rem;margin:1rem 0 1.6rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:.75rem .85rem}
.card .k{font-size:.74rem;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:1.32rem;font-weight:600;margin-top:.15rem;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:9px}
table{border-collapse:collapse;width:100%;font-size:.87rem;min-width:820px}
th,td{padding:.5rem .65rem;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--card);font-weight:600;font-size:.78rem;text-transform:uppercase;
 letter-spacing:.03em;color:var(--mut);position:sticky;top:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
tr.gold{background:color-mix(in srgb,var(--gold) 13%,transparent)}
tr.invalid{opacity:.5}
.tag{display:inline-block;padding:.08rem .45rem;border-radius:5px;font-size:.73rem;font-weight:600}
.pass{background:color-mix(in srgb,var(--acc) 20%,transparent);color:var(--acc)}
.fail{background:color-mix(in srgb,var(--bad) 20%,transparent);color:var(--bad)}
.g{color:var(--gold);font-weight:700}
.neg{color:var(--acc)} .pos{color:var(--bad)}
details{margin:.4rem 0;border:1px solid var(--line);border-radius:8px;background:var(--card)}
summary{cursor:pointer;padding:.55rem .8rem;font-weight:600;font-size:.9rem}
details .body{padding:0 .8rem .8rem}
pre{margin:.4rem 0;padding:.6rem .7rem;background:var(--bg);border:1px solid var(--line);
 border-radius:6px;overflow-x:auto;font-size:.8rem;line-height:1.45}
.note{border-left:3px solid var(--gold);padding:.55rem .8rem;background:var(--card);
 border-radius:0 7px 7px 0;margin:.9rem 0;font-size:.9rem}
"""


def _fmt(v, n=5):
    return "-" if v is None else f"{v:.{n}f}"


def build():
    gens = generation.all_generations()
    if not gens:
        raise SystemExit("세대가 없다. explore.py --baseline 을 먼저 실행할 것.")
    golden = generation.current_golden()
    base = gens[0]
    base_r = base["result"].get("R_th")

    valid = [g for g in gens if g["valid"] and g["result"].get("R_th") is not None]
    best = min(valid, key=lambda g: g["result"]["R_th"]) if valid else None

    rows = []
    for g in gens:
        r = g["result"]
        rth = r.get("R_th")
        d = None if (rth is None or not base_r) else 100 * (rth - base_r) / base_r
        cls = []
        if g["name"] == golden:
            cls.append("gold")
        if not g["valid"]:
            cls.append("invalid")
        dcls = "" if d is None else ("neg" if d < 0 else "pos")
        steps = g["mesh_gate"].get("steps", [])
        p = g["params"]
        mo = g["mesh_gate"].get("model_options", {})
        assum = (f"aniso={'ON' if mo.get('anisotropic') else 'OFF'} "
                 f"제약={'ON' if mo.get('process_constraints') else 'OFF'} "
                 f"h={mo.get('h_model', '?')}"
                 + (f" -{len(mo.get('disabled_rules') or [])}규칙"
                    if mo.get("disabled_rules") else "")) if mo else "(미기록)"
        heff = mo.get("h_effective")
        cl = g["mesh_gate"].get("coolant", {})
        mat = f"{p.get('hs_material','?')} / {p.get('tim_material','?')}"
        struct = (f"r={p.get('r_pin',0)*1e6:.0f} h={p.get('h_pin',0)*1e6:.0f} "
                  f"n={p.get('n','?')} tb={p.get('t_base',0)*1e6:.0f}")
        rows.append(f"""<tr class="{' '.join(cls)}">
<td>{'<span class="g">GOLDEN</span> ' if g['name']==golden else ''}{html.escape(g['name'])}</td>
<td>{html.escape(mat)}</td>
<td>{html.escape(struct)}</td>
<td>{html.escape(assum)}</td>
<td class="num">{_fmt(rth)}</td>
<td class="num {dcls}">{'-' if d is None else f'{d:+.2f}%'}</td>
<td class="num">{_fmt(r.get('Q_conv'),4)}</td>
<td class="num">{_fmt((r.get('A_conv') or 0)*1e6,4)}</td>
<td class="num">{'-' if heff is None else f'{heff:,.0f}'}</td>
<td class="num">{_fmt(cl.get('Re_max'),1) if cl.get('Re_max') is not None else '-'}</td>
<td><span class="tag {'pass' if g['valid'] else 'fail'}">{'PASS' if g['valid'] else 'FAIL'}</span></td>
<td class="num">{len(steps)}</td>
<td>{html.escape(g['parent'] or '-')}</td></tr>""")

    details = []
    for g in gens:
        steps = g["mesh_gate"].get("steps", [])
        lines = []
        for s in steps:
            if "error" in s:
                lines.append(f"  hmax {s['hmax']*1e6:5.0f} um  오류: {s['error'][:90]}")
            else:
                dd = "" if s.get("delta_pct") is None else f"{s['delta_pct']:+8.4f}%"
                lines.append(f"  hmax {s['hmax']*1e6:5.0f} um  R_th={s['R_th']:9.5f}  "
                             f"nodes={s['nodes']:7d}  {dd:>9}  {s.get('wall_s','?')}s")
        details.append(f"""<details><summary>{html.escape(g['name'])}</summary><div class="body">
<pre>{html.escape(json.dumps(g['params'], indent=2, ensure_ascii=False))}</pre>
<b>메시 수렴 게이트</b> — {html.escape(g['mesh_gate'].get('criterion',''))}
<pre>{html.escape(chr(10).join(lines) or '(단계 없음)')}</pre></div></details>""")

    note = ""
    if best and base_r:
        imp = 100 * (best["result"]["R_th"] - base_r) / base_r
        note = (f'<div class="note"><b>현재 최상위 후보</b>: {html.escape(best["name"])} — '
                f'R_th {best["result"]["R_th"]:.5f} K/W ({imp:+.2f}% vs 기준). '
                f'골든 승격은 자동으로 되지 않는다: <code>python promote.py '
                f'{html.escape(best["name"])}</code></div>')

    body = f"""<div class="wrap">
<h1>HBM 핀히트싱크 세대 히스토리</h1>
<p class="sub">기준 세대 {html.escape(base['name'])} · 현재 골든 {html.escape(golden or '(미지정)')} ·
메시 수렴 게이트를 통과한 세대만 비교 대상이다</p>
<div class="cards">
<div class="card"><div class="k">전체 세대</div><div class="v">{len(gens)}</div></div>
<div class="card"><div class="k">게이트 통과</div><div class="v">{len(valid)}</div></div>
<div class="card"><div class="k">기준 R_th</div><div class="v">{_fmt(base_r,3)}</div></div>
<div class="card"><div class="k">최상위 R_th</div><div class="v">{_fmt(best['result']['R_th'],3) if best else '-'}</div></div>
</div>
{note}
<h2>세대 목록</h2>
<div class="scroll"><table>
<thead><tr><th>세대</th><th>재료 (히트싱크/TIM)</th><th>구조 [um]</th><th>모델 가정</th><th>R_th [K/W]</th>
<th>vs 기준</th><th>Q [W]</th><th>A [mm2]</th><th>h [W/m2K]</th><th>Re_max</th><th>게이트</th><th>메시단계</th><th>부모</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>세대별 상세 (파라미터 + 게이트 증거)</h2>
{''.join(details)}
</div>"""

    out = ws.WS / "out" / "history.html"
    out.write_text(f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
                   f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
                   f"<title>HBM 핀히트싱크 세대 히스토리</title><style>{CSS}</style></head>"
                   f"<body>{body}</body></html>")
    return out, len(gens), len(valid)


if __name__ == "__main__":
    p, n, v = build()
    print(f"{p}  (세대 {n}개, 게이트 통과 {v}개)")
