# 후보 1건을 평가한다 - 메시 수렴 게이트를 통과시킨 뒤에야 결과를 인정한다
"""
세대 간 비교가 공정하려면 각 세대가 '자기 형상에서 수렴한' 메시로 풀려야 한다.
메시를 고정하고 형상만 바꾸면, 형상에 따라 이산화 오차가 달라져 순위가 오염된다.

절차:
  1. 설계 제약 검사 (params.check) - 위반이면 즉시 탈락, solve 안 함
  2. 메시를 단계적으로 조밀하게 하며 R_th 를 추적
  3. 인접 두 단계의 상대변화가 tol 이내면 통과. 아니면 다음 단계로.
  4. 마지막까지 수렴 안 하면 INVALID (결과는 남기되 신뢰 불가로 표시)

성공 마커만 보지 않는다 - 각 단계의 실패를 그대로 기록한다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import constraints                       # noqa: E402
import coolant                           # noqa: E402
from backend import skfem_thermal as bk  # noqa: E402
from geom import stack                   # noqa: E402
from params import Params                # noqa: E402

um = 1e-6
# 거친 -> 조밀. 앞 단계에서 수렴하면 뒤는 돌지 않는다 (비용 절약).
MESH_LADDER = [120 * um, 85 * um, 60 * um, 42 * um, 30 * um]
DEFAULT_TOL = 1.0   # %


def evaluate(pm: Params, tol: float = DEFAULT_TOL, workdir=None,
             ladder=None, keep_mesh=False):
    """후보 1건 평가. 반환 (result, mesh_gate).

    result 가 None 이면 설계 제약 위반으로 아예 풀지 않은 것이다.
    """
    bad = pm.check()
    if bad:
        return None, {"passed": False, "rejected": bad,
                      "criterion": "기하 제약 위반 - solve 미실시", "steps": []}

    # 공정 제약은 별도 층이다. 스위치로 끌 수 있고, 껐다는 사실이 기록된다.
    viol, applied = constraints.check(pm, pm.process_constraints, pm.disabled_rules)
    if viol:
        return None, {"passed": False,
                      "rejected": [v["reason"] for v in viol],
                      "violated_rules": [v["rule"] for v in viol],
                      "criterion": "공정 제약 위반 - solve 미실시",
                      "steps": []}

    # 냉각 모델: h 를 형상의 함수로 정한다 (h_model="fixed" 면 상수 그대로).
    h_eff, hdiag = coolant.effective_h(pm)
    if h_eff is None:
        return None, {"passed": False,
                      "rejected": [hdiag.get("error", "h 계산 실패")],
                      "criterion": "냉각 모델 해 없음 - solve 미실시",
                      "coolant": hdiag, "steps": []}
    pm = pm.with_(h_conv=h_eff)

    ladder = ladder or MESH_LADDER
    import workspace as ws
    wd = Path(workdir) if workdir else (ws.WS / "runs" / "_eval")
    wd.mkdir(parents=True, exist_ok=True)

    steps = []
    prev = None
    result = None
    passed = False
    for h in ladder:
        msh = wd / f"m{int(h*1e6)}.msh"
        t0 = time.time()
        try:
            info = stack.generate(pm, str(msh), mesh_size=h)
            r = bk.solve_case(str(msh), info["vol_props"], pm)
        except Exception as exc:
            steps.append({"hmax": h, "error": str(exc)})
            continue
        finally:
            if not keep_mesh:
                msh.unlink(missing_ok=True)

        d = None if prev is None else abs(r["R_th"] - prev) / prev * 100
        steps.append({"hmax": h, "R_th": r["R_th"], "Q_conv": r["Q_conv"],
                      "nodes": info["n_nodes"], "tets": info["n_tets"],
                      "delta_pct": d, "wall_s": round(time.time() - t0, 2)})
        result = r
        if d is not None and d < tol:
            passed = True
            break
        prev = r["R_th"]

    gate = {
        "passed": passed,
        "criterion": f"인접 메시 단계의 R_th 상대변화 < {tol}%",
        "tol_pct": tol,
        "steps": steps,
        "coolant": hdiag,
        "model_options": {
            "h_model": pm.h_model,
            "h_effective": h_eff,
            "anisotropic": pm.anisotropic,
            "hs_orientation": pm.hs_orientation,
            "process_constraints": pm.process_constraints,
            "disabled_rules": list(pm.disabled_rules),
            "constraints_applied": applied,
        },
    }
    if not passed and result is not None:
        gate["note"] = "사다리 끝까지 수렴하지 않았다 - 결과는 참고용이며 세대 비교에 쓰면 안 된다"
    return result, gate


if __name__ == "__main__":
    pm = Params()
    r, gate = evaluate(pm)
    print(f"게이트: {'PASS' if gate['passed'] else 'FAIL'}  ({gate['criterion']})")
    for s in gate["steps"]:
        if "error" in s:
            print(f"  hmax {s['hmax']*1e6:5.0f} um  오류: {s['error'][:70]}")
        else:
            d = "" if s["delta_pct"] is None else f"{s['delta_pct']:+7.4f}%"
            print(f"  hmax {s['hmax']*1e6:5.0f} um  R_th={s['R_th']:9.5f}  "
                  f"nodes={s['nodes']:7d}  {d:>9}  {s['wall_s']:5.2f}s")
    if r:
        print(f"\nR_th={r['R_th']:.5f} K/W  Q={r['Q_conv']:.5f} W  "
              f"A={r['A_conv']*1e6:.4f} mm^2")
