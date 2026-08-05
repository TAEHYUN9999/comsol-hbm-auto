# flow_gap 제약선 위를 훑어 진짜 최적을 찾고, 그 스펙에 대한 민감도를 잰다
"""
refine.py 가 최적점이 flow_gap 제약선 위에 얹혀 있음을 확인했다.
그렇다면 최적은 격자를 조밀하게 해서 찾을 게 아니라 제약선 자체를 따라가야 한다.

제약선: p = 2*r_pin + gap_min

이 선 위에서 r_pin 만 바꾸면 (p, n 은 종속) 1차원 문제가 된다.
  r 작음 -> 핀 가늘고 촘촘, 개수 많음, 면적 큼, 핀효율 낮음
  r 큼   -> 핀 굵고 성김, 개수 적음, 면적 작음, 핀효율 높음
여기에 진짜 극값이 있다.

그리고 gap_min 은 제가 정한 값이 아니라 냉각 방식에서 오는 스펙이므로,
여러 gap_min 에 대해 최적을 구해 '스펙이 답을 얼마나 흔드는지'를 같이 낸다.

사용: python line_search.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import constraints as C          # noqa: E402
from evaluate import evaluate    # noqa: E402
from params import Params        # noqa: E402

import workspace as ws

ROOT = ws.WS
um = 1e-6

GAP_SPECS = [30, 40, 50, 70, 100, 150]     # 조사할 MIN_FLOW_GAP [um]
R_VALS = list(range(40, 141, 5))           # 제약선 위 r_pin [um]
H_PIN = 600 * um
T_BASE = 50 * um


def max_n(pm):
    best = None
    for n in range(2, 16):
        p2 = pm.with_(n=n)
        if p2.check():
            continue
        viol, _ = C.check(p2, enabled=True)
        if viol:
            continue
        best = n
    return best


def scan(base, gap_um):
    C.set_limits(MIN_FLOW_GAP=gap_um * um)
    out = []
    for r in R_VALS:
        p = 2 * r + gap_um
        pm = base.with_(r_pin=r * um, p=p * um)
        n = max_n(pm)
        if n is None:
            continue
        pm = pm.with_(n=n)
        res, gate = evaluate(pm)
        if res is None or not gate["passed"]:
            continue
        out.append({
            "r": r, "p": p, "n": n, "pins": n * n,
            "R_th": res["R_th"], "Q": res["Q_conv"],
            "area_ratio": res["area_ratio"],
            "foot_use": res["footprint_use"],
            "h": gate["model_options"]["h_effective"],
            "Re": (gate.get("coolant") or {}).get("Re_max"),
        })
    return out


def main():
    goal = json.loads((ws.WS / "goal.json").read_text())
    lim = {k: v for k, v in goal.get("limits", {}).items() if not k.startswith("_")}
    if lim:
        C.set_limits(**lim)
    mo = goal["model_options"]
    base = ws.base_params().with_(h_model="pumping_power",
                                  coolant=mo.get("coolant", "water"),
                                  p_pump=mo["p_pump"], h_pin=H_PIN, t_base=T_BASE)

    print(f"flow_gap 제약선 위 탐색   h_pin={H_PIN*1e6:.0f}um  t_base={T_BASE*1e6:.0f}um  "
          f"냉각={mo['coolant']}  펌핑={mo['p_pump']:.3e} W")
    print(f"제약선: p = 2*r_pin + gap\n")

    summary = []
    for gap in GAP_SPECS:
        rows = scan(base, gap)
        if not rows:
            print(f"gap={gap}um : 유효 케이스 없음")
            continue
        b = min(rows, key=lambda x: x["R_th"])
        edge = b["r"] in (rows[0]["r"], rows[-1]["r"])
        summary.append((gap, b, edge, len(rows)))

        print(f"--- MIN_FLOW_GAP = {gap} um  ({len(rows)}점) ---")
        print(f"{'r[um]':>6} {'p[um]':>6} {'n':>3} {'핀수':>5} {'R_th':>9} "
              f"{'면적증배':>9} {'h':>9} {'Re':>7}")
        for x in rows:
            mark = " <-" if x is b else ""
            print(f"{x['r']:6d} {x['p']:6d} {x['n']:3d} {x['pins']:5d} "
                  f"{x['R_th']:9.4f} {x['area_ratio']:9.2f} {x['h']:9.0f} "
                  f"{(x['Re'] or 0):7.1f}{mark}")
        print(f"  최적 r={b['r']}um p={b['p']}um n={b['n']} -> R_th={b['R_th']:.4f}"
              f"   {'[격자 끝 - 범위 확장 필요]' if edge else '[진짜 내부 극값]'}\n")

    print("=" * 72)
    print("MIN_FLOW_GAP 스펙이 최적 형상에 미치는 영향")
    print(f"{'gap[um]':>8} {'최적 r':>8} {'최적 p':>8} {'n':>4} {'핀수':>6} "
          f"{'R_th':>9} {'vs원본':>9} {'극값?':>8}")
    base_rth = 23.79890
    for gap, b, edge, _ in summary:
        print(f"{gap:8d} {b['r']:7d}um {b['p']:7d}um {b['n']:4d} {b['pins']:6d} "
              f"{b['R_th']:9.4f} {100*(b['R_th']-base_rth)/base_rth:+8.2f}% "
              f"{'격자끝' if edge else '내부':>8}")
    if summary:
        rs = [b["R_th"] for _, b, _, _ in summary]
        print(f"\n스펙 30~150um 구간에서 R_th 가 {min(rs):.3f} ~ {max(rs):.3f} K/W "
              f"({100*(max(rs)-min(rs))/min(rs):.1f}% 폭) 로 변한다.")
        print("이 스펙 없이 최적 형상을 확정할 수 없다.")


if __name__ == "__main__":
    main()
