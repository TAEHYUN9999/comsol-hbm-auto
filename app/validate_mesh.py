# 메시 수렴성 게이트 - 이 시험을 통과하지 못하면 어떤 최적화 결과도 무의미하다
"""
메시를 단계적으로 조밀하게 만들며 R_th / Q_conv 가 수렴하는지 본다.
판정: 인접한 두 단계의 R_th 상대변화가 1% 이내로 들어오면 통과.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from params import Params          # noqa: E402
from geom import stack             # noqa: E402
from backend import skfem_thermal as bk  # noqa: E402

um = 1e-6
SIZES = [150 * um, 120 * um, 90 * um, 70 * um, 55 * um, 42 * um]


def main():
    pm = Params()
    rows = []
    print(f"{'hmax[um]':>9} {'nodes':>9} {'tets':>10} {'R_th[K/W]':>11} "
          f"{'Q[W]':>9} {'T_min[K]':>10} {'dR%':>8} {'t[s]':>7}")
    prev = None
    for s in SIZES:
        t0 = time.time()
        try:
            info = stack.generate(pm, f"runs/_mesh/{int(s*1e6)}.msh", mesh_size=s)
            r = bk.solve_case(f"runs/_mesh/{int(s*1e6)}.msh", info["vol_props"], pm)
        except Exception as exc:
            print(f"{s*1e6:9.0f}  실패: {exc}")
            continue
        dt = time.time() - t0
        d = "" if prev is None else f"{100*(r['R_th']-prev)/prev:+8.3f}"
        print(f"{s*1e6:9.0f} {info['n_nodes']:9d} {info['n_tets']:10d} "
              f"{r['R_th']:11.5f} {r['Q_conv']:9.4f} {r['T_min']:10.3f} {d:>8} {dt:7.1f}")
        rows.append((s, info, r))
        prev = r["R_th"]

    if len(rows) >= 2:
        a, b = rows[-2][2]["R_th"], rows[-1][2]["R_th"]
        err = abs(b - a) / a * 100
        print(f"\n최종 두 단계 R_th 상대차: {err:.3f}%  -> "
              f"{'PASS (1% 이내)' if err < 1.0 else 'FAIL (미수렴, 더 조밀한 메시 필요)'}")
    return rows


if __name__ == "__main__":
    main()
