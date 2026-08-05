# 오픈소스 백엔드를 COMSOL 기준값에 맞춘다 - 자동화가 신뢰를 얻는 유일한 지점
"""
왜 필요한가:
  탐색 루프는 오픈소스 백엔드(gmsh + scikit-fem)로 돈다. COMSOL 1케이스가
  약 10분인데 루프는 수백~수천 케이스를 돌려야 하므로 다른 선택지가 없다.
  대신 그 빠른 모델이 COMSOL 과 얼마나 다른지를 모르면 결과를 믿을 수 없다.

무엇을 맞추나:
  다이스택 유효물성은 TSV/범프를 층 단위 이방성으로 치환한다. 이 치환은
  넓은 다이에서 좁은 범프로 열이 모였다 퍼지는 **수축(constriction) 저항**을
  무시하므로 스택을 실제보다 잘 통하게 만든다.
  그 몫을 스칼라 하나(stack_k_factor)로 흡수해 COMSOL 기준값에 맞춘다.

  이는 h 를 펌핑파워 앵커로 맞춘 것과 같은 방식이다 - 물리를 더 넣는 대신
  측정 가능한 기준점 하나에 모델을 고정한다.

기준값 얻는 법 (COMSOL 에서 1회):
  결과 > 파생값 > 최대/최소 값  -> T_max, T_min
  결과 > 파생값 > 적분 > 표면적분, 대류 경계, 표현식 ht.ntflux -> Q [W]
  R_th = (T_hot - T_ext) / Q

사용:
  python calibrate.py --tmin 313.13
  python calibrate.py --rth 31.5 --geom r_pin=75 p=301 n=4 h_pin=300 t_base=100
  python calibrate.py --show
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workspace as ws          # noqa: E402
from evaluate import evaluate   # noqa: E402
from params import Params       # noqa: E402

um = 1e-6
TARGETS = {"tmin": "T_min", "tmax": "T_max", "rth": "R_th", "q": "Q_conv"}


def parse_geom(items):
    out = {}
    for s in items or []:
        k, _, v = s.partition("=")
        if k == "n":
            out[k] = int(v)
        elif k in ("r_pin", "p", "h_pin", "t_base"):
            out[k] = float(v) * um
        else:
            out[k] = float(v)
    return out


def fit(target_key, target_val, base: Params, lo=0.02, hi=1.0, tol=1e-4):
    """stack_k_factor 를 조정해 target 을 맞춘다. 반환 (factor, 달성값, 이력)."""
    hist = []

    def err(f):
        r, g = evaluate(base.with_(stack_k_factor=f))
        if r is None or not g["passed"]:
            raise RuntimeError(f"기준 형상 평가 실패 (factor={f}): "
                               f"{g.get('rejected') or g.get('note')}")
        v = r[target_key]
        hist.append((f, v))
        return v - target_val

    e_lo, e_hi = err(lo), err(hi)
    if e_lo * e_hi > 0:
        raise SystemExit(
            f"목표 {target_key}={target_val} 이 계수 범위 [{lo}, {hi}] 밖이다.\n"
            f"  factor={lo} -> {hist[0][1]:.4f}\n  factor={hi} -> {hist[1][1]:.4f}\n"
            f"  기준값이나 기준 형상이 맞는지 확인할 것.")
    f = brentq(err, lo, hi, xtol=tol, rtol=1e-8)
    r, _ = evaluate(base.with_(stack_k_factor=f))
    return f, r, hist


def main():
    ap = argparse.ArgumentParser()
    for k in TARGETS:
        ap.add_argument(f"--{k}", type=float, default=None,
                        help=f"COMSOL 기준 {TARGETS[k]}")
    ap.add_argument("--geom", nargs="*", default=None,
                    help="기준 형상 (예: r_pin=75 p=301 n=4). 단위 um. 생략시 원본 기본값")
    ap.add_argument("--show", action="store_true", help="현재 캘리브레이션 상태만 출력")
    ap.add_argument("--dry-run", action="store_true", help="project.json 에 쓰지 않는다")
    a = ap.parse_args()

    ws.ensure()
    pj_path = ws.WS / "project.json"
    pj = json.loads(pj_path.read_text()) if pj_path.exists() else {}
    cal = pj.setdefault("calibration", {})

    if a.show:
        print("현재 캘리브레이션:")
        print(f"  stack_resistance_factor = {cal.get('stack_resistance_factor')}")
        print(f"  p_pump                  = {cal.get('p_pump')}")
        ref = cal.get("reference") or {}
        if ref.get("measured_at"):
            print(f"  기준값 ({ref['measured_at']}): "
                  + ", ".join(f"{k}={ref[k]}" for k in
                              ("T_max", "T_min", "Q_conv", "R_th") if ref.get(k)))
        else:
            print("  기준값 없음 -> 오픈소스 절대값은 미검증 상태다")
        return 0

    chosen = [(k, getattr(a, k)) for k in TARGETS if getattr(a, k) is not None]
    if len(chosen) != 1:
        raise SystemExit("기준값을 정확히 하나 줄 것 (--tmin / --tmax / --rth / --q)")
    key, val = chosen[0]
    tkey = TARGETS[key]

    g = ws.goal()
    mo = ws.strip_comments(g.get("model_options", {}))
    ws.apply_limits()
    base = Params().with_(**parse_geom(a.geom))
    if cal.get("p_pump"):
        base = base.with_(h_model="pumping_power",
                          coolant=mo.get("coolant", "water"),
                          p_pump=cal["p_pump"])

    print(f"기준 형상: r_pin={base.r_pin*1e6:.0f}um p={base.p*1e6:.0f}um n={base.n} "
          f"h_pin={base.h_pin*1e6:.0f}um t_base={base.t_base*1e6:.0f}um")
    print(f"목표      : {tkey} = {val}")
    print(f"h 모델    : {base.h_model}" + (f" (p_pump={base.p_pump:.4e} W)"
                                           if base.h_model == "pumping_power" else ""))
    print()

    r0, _ = evaluate(base.with_(stack_k_factor=1.0))
    print(f"보정 전 (factor=1.0): {tkey} = {r0[tkey]:.4f}   "
          f"오차 {100*(r0[tkey]-val)/val:+.2f}%")

    f, r, hist = fit(tkey, val, base)
    print(f"보정 후 (factor={f:.5f}): {tkey} = {r[tkey]:.4f}   "
          f"오차 {100*(r[tkey]-val)/val:+.4f}%")
    print(f"  탐색 {len(hist)}회")
    print()
    print("보정이 다른 값에 미친 영향:")
    for k in ("R_th", "Q_conv", "T_max", "T_min", "T_max_hs"):
        print(f"   {k:10s} {r0[k]:12.4f}  ->  {r[k]:12.4f}   "
              f"({100*(r[k]-r0[k])/r0[k]:+7.2f}%)")

    if a.dry_run:
        print("\n--dry-run: project.json 에 쓰지 않았다")
        return 0

    cal["stack_resistance_factor"] = round(f, 6)
    cal.setdefault("reference", {}).update({
        "geometry": {"r_pin_um": base.r_pin * 1e6, "p_um": base.p * 1e6, "n": base.n,
                     "h_pin_um": base.h_pin * 1e6, "t_base_um": base.t_base * 1e6},
        tkey: val,
        "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fitted_on": tkey,
    })
    pj_path.write_text(json.dumps(pj, ensure_ascii=False, indent=2))
    print(f"\nproject.json 갱신: stack_resistance_factor = {f:.6f}")
    print("주의: 기존 세대는 보정 전 모델로 계산된 것이다. "
          "재평가하려면 explore 를 다시 돌릴 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
