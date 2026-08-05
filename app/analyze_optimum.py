# D-2 판정 게이트 - 최적해가 탐색 격자 경계에 붙어 있는지 검사한다
"""
최적화가 의미를 가지려면 최적점이 탐색 범위 '안쪽'에 있어야 한다.
경계에 붙어 있다면 그건 최적해가 아니라 "범위를 더 넓히면 계속 좋아진다"는 뜻이고,
모델에 트레이드오프가 빠져 있다는 신호다.

판정:
  INTERIOR  최적점의 모든 자유변수가 격자 내부 -> 진짜 최적해
  BOUNDARY  하나라도 격자 끝값 -> 발산. 그 변수 이름을 보고한다.

사용: python analyze_optimum.py [--tag pp]
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generation  # noqa: E402

import workspace as ws

ROOT = ws.WS
VARS = ["r_pin", "h_pin", "p", "t_base", "n"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=None, help="세대 이름 접미사로 필터")
    ap.add_argument("--objective", default="R_th")
    args = ap.parse_args()

    gens = [g for g in generation.all_generations()
            if g["valid"] and g["result"].get(args.objective) is not None]
    if args.tag:
        gens = [g for g in gens if g["name"].endswith("_" + args.tag)]
    if not gens:
        raise SystemExit("해당 조건의 유효 세대가 없다")

    best = min(gens, key=lambda g: g["result"][args.objective])
    bp = best["params"]

    # 실제로 탐색된 값의 집합 (거부된 후보는 여기 없다 - 그것이 '유효 격자'다)
    grid = defaultdict(set)
    for g in gens:
        for v in VARS:
            if v in g["params"]:
                grid[v].add(g["params"][v])

    print(f"대상 세대 {len(gens)}개" + (f" (tag={args.tag})" if args.tag else ""))
    mo = best["mesh_gate"].get("model_options", {})
    print(f"모델 가정: h={mo.get('h_model','?')} aniso={mo.get('anisotropic')} "
          f"제약={mo.get('process_constraints')}")
    print(f"최적: {best['name']}   {args.objective}={best['result'][args.objective]:.5f}")
    if mo.get("h_effective"):
        print(f"       h_eff={mo['h_effective']:,.1f} W/(m^2 K)")
    print()
    print(f"{'변수':>8} {'최적값':>10} {'격자 최소':>10} {'격자 최대':>10} {'수':>4}  판정")

    # 경계 고착에는 두 종류가 있다. 이 둘을 구분하는 것이 판정의 핵심이다.
    #   GRID       탐색 격자를 넓히기만 하면 계속 좋아진다 -> 모델링 실패
    #   CONSTRAINT 그 너머는 실제 제약(공정/기하/패키지)이 막는다 -> 정상적인 답
    from params import Params
    import constraints as C
    goal = json.loads((ws.WS / "goal.json").read_text())
    lim = {k: v for k, v in goal.get("limits", {}).items() if not k.startswith("_")}
    if lim:
        C.set_limits(**lim)
    full = goal["search"]["structure"]

    def beyond_blocked(var, direction):
        """격자 밖 이웃값이 실제 제약에 막히는지 본다. 반환 (막힘여부, 사유)."""
        key = var + ("_um" if var != "n" else "")
        vals = sorted(full.get(key, []))
        if not vals:
            return None, "격자 정의 없음"
        step = (vals[-1] - vals[0]) / max(len(vals) - 1, 1)
        nxt = (vals[-1] + step) if direction == "상한" else (vals[0] - step)
        if var != "n":
            nxt *= 1e-6
        else:
            nxt = int(round(nxt))
            if nxt < 1:
                return True, "n < 1 (물리적 하한)"
        probe = Params().with_(**{k: v for k, v in bp.items()
                                  if k in Params.__dataclass_fields__})
        probe = probe.with_(**{var: nxt})
        geo = probe.check()
        if geo:
            return True, f"[기하] {geo[0]}"
        viol, _ = C.check(probe, enabled=True)
        if viol:
            return True, f"[{viol[0]['rule']}] {viol[0]['reason']}"
        return False, "제약 없음 - 격자만 넓히면 더 좋아진다"

    verdicts = []
    for v in VARS:
        vals = sorted(grid[v])
        if len(vals) < 2:
            continue
        cur = bp.get(v)
        scale = 1e6 if v != "n" else 1
        unit = "um" if v != "n" else ""
        which = ("하한" if cur == vals[0] else
                 "상한" if cur == vals[-1] else "내부")
        if which == "내부":
            kind, why = "INTERIOR", ""
        else:
            blocked, why = beyond_blocked(v, which)
            kind = "CONSTRAINT" if blocked else "GRID"
        verdicts.append((v, which, kind, why))
        print(f"{v:>8} {cur*scale:9.0f}{unit:2s} {vals[0]*scale:9.0f}{unit:2s} "
              f"{vals[-1]*scale:9.0f}{unit:2s} {len(vals):4d}  {which:4s} {kind}")

    print()
    grid_bound = [x for x in verdicts if x[2] == "GRID"]
    for v, which, kind, why in verdicts:
        if kind != "INTERIOR":
            print(f"   {v:>7} {which} 너머: {why}")
    print()
    if grid_bound:
        print(f"판정: DIVERGENT - {len(grid_bound)}개 변수가 격자 인공물에 고착")
        for v, which, _, _ in grid_bound:
            print(f"   {v} 를 {which} 밖으로 넓히면 계속 좋아진다. "
                  f"실제 상한을 정의하는 제약이 없다.")
        return 1
    print("판정: BOUNDED - 모든 경계가 실제 제약(공정/기하/패키지)에 막혀 있다.")
    print("   '가용 한도를 다 써라'는 유효한 공학적 결론이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
