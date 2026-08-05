# 설계변수 스윕 루프 - Vivado 전략 스윕의 COMSOL 판. 케이스별 판정을 JSONL 로 축적한다
"""
사용:
    python sweep.py --var r_pin --values 40,55,75,95,115 --unit um
    python sweep.py --grid r_pin=50,75,100 h_pin=200,300,400,500 --unit um

설계 제약(params.Params.check)에 걸리는 조합은 solve 없이 SKIP 하고 사유를 남긴다.
모든 목적함수를 매 케이스마다 계산해 기록하므로, 판정 기준이 나중에 바뀌어도
과거 실행을 다시 판정할 수 있다.
"""

import argparse
import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import objective                          # noqa: E402
from backend import skfem_thermal as bk   # noqa: E402
from geom import stack                    # noqa: E402
from params import Params                 # noqa: E402

UNITS = {"m": 1.0, "mm": 1e-3, "um": 1e-6, "": 1.0}
INT_VARS = {"n", "n_dram"}


def parse_grid(specs, unit):
    """['r_pin=50,75', 'h_pin=200,400'] -> [('r_pin',[...]), ('h_pin',[...])]"""
    scale = UNITS[unit]
    out = []
    for s in specs:
        name, _, vals = s.partition("=")
        if not vals:
            raise SystemExit(f"--grid 형식 오류: {s!r} (예: r_pin=50,75,100)")
        if name in INT_VARS:
            out.append((name, [int(v) for v in vals.split(",")]))
        else:
            out.append((name, [float(v) * scale for v in vals.split(",")]))
    return out


def run_case(pm, mesh_size, workdir, tag):
    msh = str(Path(workdir) / f"{tag}.msh")
    info = stack.generate(pm, msh, mesh_size=mesh_size)
    res = bk.solve_case(msh, info["vol_props"], pm)
    Path(msh).unlink(missing_ok=True)          # 메시는 케이스당 수 MB - 즉시 정리
    return info, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", nargs="+", required=True,
                    help="변수=값1,값2,... 를 하나 이상")
    ap.add_argument("--unit", default="um", choices=list(UNITS))
    ap.add_argument("--mesh-size", type=float, default=90.0, help="hmax [um]")
    ap.add_argument("--objective", default=objective.DEFAULT,
                    choices=list(objective.REGISTRY))
    ap.add_argument("--name", default=None, help="runs/ 아래 실행 이름")
    args = ap.parse_args()

    grid = parse_grid(args.grid, args.unit)
    names = [g[0] for g in grid]
    combos = list(itertools.product(*[g[1] for g in grid]))

    name = args.name or ("sweep_" + "_".join(names))
    workdir = Path(name)
    workdir.mkdir(parents=True, exist_ok=True)
    logf = workdir / "cases.jsonl"

    print(f"실행: {name}   케이스 {len(combos)}개   목적함수 {args.objective}")
    print(f"{'#':>4} " + " ".join(f"{n:>9}" for n in names)
          + f" {'R_th':>10} {'Q[W]':>9} {'T_stack':>9} {'T_hs':>9} {'A[mm2]':>9} {'t[s]':>6}  판정")

    best = None
    with logf.open("w") as fh:
        for i, combo in enumerate(combos):
            kw = dict(zip(names, combo))
            pm = Params().with_(**kw)
            shown = " ".join(
                f"{(v if n in INT_VARS else v/UNITS[args.unit]):9.1f}"
                for n, v in kw.items())

            bad = pm.check()
            if bad:
                print(f"{i:4d} {shown} {'':>10} {'':>9} {'':>9} {'':>9} {'':>9} {'':>6}  SKIP: {bad[0]}")
                fh.write(json.dumps({"i": i, "params": kw, "skip": bad}, ensure_ascii=False) + "\n")
                continue

            t0 = time.time()
            try:
                info, res = run_case(pm, args.mesh_size * 1e-6, workdir, f"c{i:04d}")
            except Exception as exc:
                print(f"{i:4d} {shown} {'':>10}  FAIL: {exc}")
                fh.write(json.dumps({"i": i, "params": kw, "error": str(exc)}, ensure_ascii=False) + "\n")
                continue
            dt = time.time() - t0

            scores = objective.evaluate_all(res, pm)
            sc = scores[args.objective]
            better = (best is None
                      or (sc.value < best[0] if sc.minimize else sc.value > best[0]))
            if better:
                best = (sc.value, kw, res)

            print(f"{i:4d} {shown} {res['R_th']:10.4f} {res['Q_conv']:9.4f} "
                  f"{res['T_max_stack']:9.3f} {res['T_max_hs']:9.3f} "
                  f"{res['A_conv']*1e6:9.4f} {dt:6.2f}  {'BEST' if better else ''}")

            fh.write(json.dumps({
                "i": i,
                "params": kw,
                "mesh": {"nodes": info["n_nodes"], "tets": info["n_tets"],
                         "hmax": args.mesh_size * 1e-6},
                "result": {k: v for k, v in res.items() if k != "T"},
                "scores": {k: s.value for k, s in scores.items()},
            }, ensure_ascii=False) + "\n")

    if best:
        print(f"\n최적 ({args.objective} {'최소' if scores[args.objective].minimize else '최대'}): "
              f"{best[0]:.5f}")
        for k, v in best[1].items():
            print(f"   {k} = {v if k in INT_VARS else f'{v*1e6:.1f} um'}")
    print(f"\n로그: {logf}")


if __name__ == "__main__":
    main()
