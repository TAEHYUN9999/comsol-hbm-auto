# 목표를 주면 구조/재료 후보를 돌며 세대로 저장하는 탐색기
"""
사용:
    python explore.py --axis materials          재료만 탐색
    python explore.py --axis structure          구조만 탐색
    python explore.py --axis materials structure  둘 다 (조합 폭발 주의)
    python explore.py --baseline                기준 세대(G000)만 등록

각 후보마다:
    설계제약 검사 -> 메시 수렴 게이트 -> solve -> 세대 저장

게이트를 통과 못 한 후보도 INVALID 로 저장한다. 실패도 계보의 일부다.
골든 승격은 하지 않는다 - promote.py 로 사용자가 명시적으로 한다.
"""

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generation                    # noqa: E402
import objective                     # noqa: E402
from evaluate import evaluate        # noqa: E402
from params import Params            # noqa: E402

import workspace as ws

ROOT = ws.WS
um = 1e-6


def load_goal():
    return json.loads((ws.WS / "goal.json").read_text())


def candidates(goal, axes):
    """탐색 축에서 후보 dict 리스트를 만든다."""
    s = goal["search"]
    space = {}
    if "materials" in axes:
        # '_' 로 시작하는 키는 설명 주석이다 - 탐색 변수가 아니다
        space.update({k: v for k, v in s["materials"].items() if not k.startswith("_")})
    if "structure" in axes:
        for k, vals in s["structure"].items():
            if k.startswith("_"):
                continue
            if k.endswith("_um"):
                space[k[:-3]] = [v * um for v in vals]
            else:
                space[k] = vals
    keys = list(space)
    return [dict(zip(keys, c)) for c in itertools.product(*[space[k] for k in keys])]


def fmt(k, v):
    return f"{v*1e6:.0f}um" if isinstance(v, float) and abs(v) < 1 else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--axis", nargs="+", default=["materials"],
                    choices=["materials", "structure"])
    ap.add_argument("--baseline", action="store_true",
                    help="원본 조건을 G000 기준 세대로 등록하고 종료")
    ap.add_argument("--limit", type=int, default=None, help="후보 수 상한")
    # --- 모델 가정 스위치 (Vivado impl 전략 고르듯) ---
    ap.add_argument("--anisotropy", choices=["on", "off"], default=None,
                    help="이방성 재료를 이방성으로 풀 것인가 (기본: goal.json)")
    ap.add_argument("--constraints", choices=["on", "off"], default=None,
                    help="공정 제약 필터 적용 여부 (기본: goal.json)")
    ap.add_argument("--orientation", choices=["z", "xy"], default=None,
                    help="이방성 히트싱크의 고전도축")
    ap.add_argument("--disable-rule", nargs="*", default=None,
                    help="개별 공정 제약 규칙을 끈다")
    ap.add_argument("--h-model", choices=["fixed", "velocity", "pumping_power"],
                    default=None, help="대류계수 모델 (기본: goal.json)")
    ap.add_argument("--coolant", choices=["water", "FC72", "air"], default=None)
    ap.add_argument("--p-pump", type=float, default=None, help="펌핑파워 [W]")
    ap.add_argument("--v-inf", type=float, default=None, help="접근 유속 [m/s]")
    ap.add_argument("--tag", default=None, help="세대 이름에 붙일 접미사")
    args = ap.parse_args()

    goal = load_goal()
    lim = {k: v for k, v in goal.get("limits", {}).items() if not k.startswith("_")}
    if lim:
        import constraints as C
        C.set_limits(**lim)
    tol = goal.get("mesh_tol_pct", 1.0)
    obj_name = goal.get("objective", objective.DEFAULT)

    mo = goal.get("model_options", {})
    opts = {
        "anisotropic": (args.anisotropy == "on") if args.anisotropy
                       else mo.get("anisotropic_materials", True),
        "process_constraints": (args.constraints == "on") if args.constraints
                               else mo.get("process_constraints", True),
        "hs_orientation": args.orientation or mo.get("hs_orientation", "z"),
        "disabled_rules": tuple(args.disable_rule if args.disable_rule is not None
                                else mo.get("disabled_rules", [])),
        "h_model": args.h_model or mo.get("h_model", "fixed"),
        "coolant": args.coolant or mo.get("coolant", "water"),
    }
    if args.p_pump is not None:
        opts["p_pump"] = args.p_pump
    elif mo.get("p_pump") is not None:
        opts["p_pump"] = mo["p_pump"]
    if args.v_inf is not None:
        opts["v_inf"] = args.v_inf
    elif mo.get("v_inf") is not None:
        opts["v_inf"] = mo["v_inf"]

    # 캘리브레이션(스택 보정계수)을 반드시 실어야 한다. Params() 직접 사용 금지.
    base = ws.base_params().with_(**opts)
    print(f"모델 가정: 이방성={'ON' if opts['anisotropic'] else 'OFF'}  "
          f"공정제약={'ON' if opts['process_constraints'] else 'OFF'}  "
          f"배향={opts['hs_orientation']}  h모델={opts['h_model']}"
          + (f"({opts['coolant']})" if opts["h_model"] != "fixed" else "")
          + (f"  끈 규칙={','.join(opts['disabled_rules'])}" if opts["disabled_rules"] else ""))

    if args.baseline:
        r, gate = evaluate(base, tol=tol)
        name = generation.save(
            "baseline", base, r, gate, changed={},
            rationale="원본 .mph 조건 (직경 150um, 높이 300um). 모든 세대의 비교 기준.",
            parent=None)
        print(f"기준 세대 등록: {name}  "
              f"R_th={r['R_th']:.5f}  게이트={'PASS' if gate['passed'] else 'FAIL'}")
        return

    gens = generation.all_generations()
    parent = gens[0]["name"] if gens else None
    if parent is None:
        raise SystemExit("기준 세대가 없다. 먼저 --baseline 을 실행할 것.")
    base_r = gens[0]["result"].get("R_th")

    cands = candidates(goal, args.axis)
    if args.limit:
        cands = cands[:args.limit]
    print(f"탐색 축: {', '.join(args.axis)}   후보 {len(cands)}개   "
          f"목적함수 {obj_name}   기준 R_th={base_r:.5f}")
    print(f"{'#':>4} {'후보':<42} {'R_th':>10} {'vs기준%':>9} {'게이트':>7}  세대")

    rows = []
    rejected = []
    for i, kw in enumerate(cands):
        pm = base.with_(**kw)
        desc = " ".join(f"{k}={fmt(k,v)}" for k, v in kw.items())
        if pm == base:
            print(f"{i:4d} {desc:<42} {'':>10} {'':>9} {'SKIP':>7}  (기준과 동일)")
            continue

        r, gate = evaluate(pm, tol=tol)
        if r is None:
            rule = (gate.get("violated_rules") or ["기하"])[0]
            print(f"{i:4d} {desc:<42} {'':>10} {'':>9} {'REJECT':>7}  "
                  f"[{rule}] {gate['rejected'][0][:52]}")
            rejected.append((desc, rule, gate["rejected"][0]))
            continue

        changed = {k: (getattr(base, k), v) for k, v in kw.items()}
        label = "_".join(f"{k}{fmt(k,v)}" for k, v in kw.items())[:40]
        if args.tag:
            label = f"{label}_{args.tag}"
        name = generation.save(
            label, pm, r, gate, changed=changed,
            rationale=f"{', '.join(args.axis)} 축 탐색: " + desc,
            parent=parent)

        d = 100 * (r["R_th"] - base_r) / base_r
        print(f"{i:4d} {desc:<42} {r['R_th']:10.5f} {d:+9.2f} "
              f"{'PASS' if gate['passed'] else 'FAIL':>7}  {name}")
        rows.append((r["R_th"], gate["passed"], name, desc, d))

    valid = [x for x in rows if x[1]]
    if valid:
        valid.sort()
        print(f"\n상위 5 (R_th 낮은 순, 게이트 통과분만):")
        for rth, _, name, desc, d in valid[:5]:
            print(f"   {rth:9.5f} K/W  ({d:+6.2f}%)  {desc}   [{name}]")
        print(f"\n골든 승격은 자동으로 하지 않는다. "
              f"확인 후: python promote.py {valid[0][2]}")
    inval = [x for x in rows if not x[1]]
    if inval:
        print(f"\n게이트 미통과 {len(inval)}건 - INVALID 로 저장됨 (비교에 쓰지 말 것)")

    if rejected:
        from collections import Counter
        c = Counter(r[1] for r in rejected)
        print(f"\n공정/기하 제약으로 탈락 {len(rejected)}건 (solve 미실시):")
        for rule, cnt in c.most_common():
            print(f"   {cnt:4d}건  {rule}")
        print("   제약을 끄고 물리적 상한을 보려면: --constraints off "
              "또는 --disable-rule <규칙명>")


if __name__ == "__main__":
    main()
