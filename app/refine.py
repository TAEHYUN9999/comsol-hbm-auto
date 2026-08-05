# 최적점 주변 국소 정밀 탐색 - 1D 투영으로는 안 보이는 결합 제약을 판별한다
"""
analyze_optimum 은 변수를 하나씩 1D 로 본다. 그래서 flow_gap 처럼 두 변수를
묶어 제약하는 규칙 위에 최적점이 얹혀 있으면 각 투영에서 '내부'로 잘못 보인다.

이 스크립트는 (r_pin, p) 평면을 조밀하게 훑어, 최적점이
  - 제약선에서 떨어진 진짜 내부 극값인지
  - 제약선에 붙어 미끄러진 것인지
를 구분한다. 후자면 그 제약이 사실상 설계를 결정하고 있다는 뜻이다.

사용: python refine.py
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

# 최적점 주변
R_VALS = [75, 85, 95, 105, 115, 125, 135]
P_VALS = [210, 230, 250, 270, 301, 330, 370]
H_PIN = 600 * um
T_BASE = 50 * um


def best_n(pm):
    """풋프린트에 들어가는 최대 n 을 고른다 (면적을 최대한 쓴다)."""
    best = None
    for n in range(2, 12):
        p2 = pm.with_(n=n)
        if p2.check():
            continue
        viol, _ = C.check(p2, enabled=True)
        if viol:
            continue
        best = n
    return best


def main():
    goal = json.loads((ws.WS / "goal.json").read_text())
    lim = {k: v for k, v in goal.get("limits", {}).items() if not k.startswith("_")}
    if lim:
        C.set_limits(**lim)
    mo = goal["model_options"]

    base = ws.base_params().with_(h_model="pumping_power",
                                  coolant=mo.get("coolant", "water"),
                                  p_pump=mo["p_pump"], h_pin=H_PIN, t_base=T_BASE)

    print(f"(r_pin, p) 평면 정밀 탐색   h_pin={H_PIN*1e6:.0f}um  t_base={T_BASE*1e6:.0f}um")
    print(f"flow_gap 제약선: p - 2*r_pin >= {C.MIN_FLOW_GAP*1e6:.0f}um")
    print()
    hdr = "r\\p  " + "".join(f"{p:>9}" for p in P_VALS)
    print(hdr)

    grid = {}
    for r in R_VALS:
        row = f"{r:4d} "
        for p in P_VALS:
            pm = base.with_(r_pin=r * um, p=p * um)
            n = best_n(pm)
            if n is None:
                row += f"{'--':>9}"
                continue
            pm = pm.with_(n=n)
            res, gate = evaluate(pm)
            if res is None or not gate["passed"]:
                row += f"{'x':>9}"
                continue
            grid[(r, p)] = (res["R_th"], n, res.get("area_ratio"),
                            gate["model_options"]["h_effective"])
            row += f"{res['R_th']:9.3f}"
        print(row)

    if not grid:
        raise SystemExit("유효 케이스 없음")

    (r0, p0), (rth0, n0, ar0, h0) = min(grid.items(), key=lambda kv: kv[1][0])
    gap0 = (p0 - 2 * r0)
    print()
    print(f"국소 최적: r_pin={r0}um  p={p0}um  n={n0}  R_th={rth0:.4f}  "
          f"n_pins={n0**2}  면적증배={ar0:.2f}x  h={h0:,.0f}")
    print(f"           유로폭 = p - 2r = {gap0}um  (제약 하한 {C.MIN_FLOW_GAP*1e6:.0f}um)")
    print()

    slack = gap0 - C.MIN_FLOW_GAP * 1e6
    step_r = R_VALS[1] - R_VALS[0]
    if slack <= step_r * 2:
        print(f"판정: 제약선에 붙어 있다 (여유 {slack:.0f}um <= 격자 2스텝)")
        print("   flow_gap 이 사실상 설계를 결정하고 있다. 이 값이 바뀌면 최적형상이 바뀐다.")
        print("   -> MIN_FLOW_GAP 은 냉각 방식/유체에서 오는 실제 스펙이어야 한다.")
        verdict = "CONSTRAINT-RIDING"
    else:
        print(f"판정: 진짜 내부 극값 (제약선에서 {slack:.0f}um 떨어져 있음)")
        verdict = "TRUE-INTERIOR"

    # 1D 절단면으로 볼록성 확인
    print()
    print("최적점 통과 절단면:")
    for label, fixed, varying in [("r 고정", ("r", r0), P_VALS), ("p 고정", ("p", p0), R_VALS)]:
        cells = []
        for v in varying:
            key = (r0, v) if fixed[0] == "r" else (v, p0)
            cells.append(f"{grid[key][0]:8.3f}" if key in grid else f"{'--':>8}")
        print(f"  {label} {fixed[1]:3d}um: " + " ".join(cells))
    return verdict


if __name__ == "__main__":
    print("\n결과:", main())
