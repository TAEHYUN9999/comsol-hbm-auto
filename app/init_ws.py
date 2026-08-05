# 작업공간을 초기화하고 원본 모델을 등록/검사한다
"""
사용:
  python init_ws.py                          작업공간만 생성
  python init_ws.py --source-mph <원본.mph>  원본 등록 + 파라메트릭 검사
  python init_ws.py --status                 현재 상태 요약
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workspace as ws  # noqa: E402


def status():
    print(f"작업공간 : {ws.WS}")
    if not ws.WS.exists():
        print("  (없음) -- init_ws.py 로 생성할 것")
        return 1
    pj = ws.project() if (ws.WS / "project.json").exists() else {}
    g = ws.goal() if (ws.WS / "goal.json").exists() else {}
    src = pj.get("source_mph")
    print(f"  원본 mph : {src or '(미등록)'}")
    if src and not Path(src).exists():
        print("     경고: 경로에 파일이 없다")
    print(f"  COMSOL   : {ws.comsol_cmd() or '(못 찾음 - COMSOL_ROOT/COMSOL_CMD 설정 필요)'}")
    cal = pj.get("calibration", {})
    ref = cal.get("reference") or {}
    print(f"  캘리브레이션 : factor={cal.get('stack_resistance_factor')} "
          f"p_pump={cal.get('p_pump')}")
    if not ref.get("measured_at"):
        print("     기준값 없음 -> 절대값 미검증. 개선은 절대값(K/W)으로 보고할 것")
    else:
        print(f"     기준 {ref.get('measured_at')} ({ref.get('fitted_on')})")
    print(f"  목적함수 : {g.get('objective')}")
    lim = ws.strip_comments(g.get("limits", {}))
    if lim:
        print("  제약 :", ", ".join(f"{k}={v}" for k, v in lim.items()))
    gens = list((ws.WS / "generations").glob("G*")) if (ws.WS / "generations").exists() else []
    print(f"  세대 : {len(gens)}개")
    import generation
    gname = generation.current_golden()
    if gname:
        print(f"  골든 : {gname}")
    out = sorted((ws.WS / "out").glob("*.mph")) if (ws.WS / "out").exists() else []
    if out:
        print("  산출 mph :", ", ".join(p.name for p in out))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-mph", default=None)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    if a.status:
        return status()

    ws.ensure()
    print(f"작업공간 준비: {ws.WS}")
    for sub in ("generations", "runs", "out"):
        print(f"   {sub}/")

    if a.source_mph:
        src = Path(a.source_mph).expanduser().resolve()
        if not src.exists():
            raise SystemExit(f"원본 mph 없음: {src}")
        print(f"\n원본 모델 검사: {src.name}")
        import inspect_mph
        r = inspect_mph.analyze(src)
        pf = r["parametric_features"]
        print(f"   전역 매개변수 {len(r['parameters'])}개, "
              f"지오메트리 feature {len(r['geometry_features'])}개")
        print(f"   매개변수를 참조하는 feature {len(pf)}개")
        print(f"   스터디 {r['studies']}")
        if not pf:
            print("\n판정: 형상이 매개변수를 따라가지 않는다 (CAD 임포트 추정).")
            print("      -pname/-plist 주입으로 형상이 바뀌지 않으므로 자동화할 수 없다.")
            return 1

        pj_path = ws.WS / "project.json"
        pj = json.loads(pj_path.read_text())
        pj["source_mph"] = str(src)
        if r["studies"]:
            pj["study_tag"] = r["studies"][0]
        # 히트싱크 형상을 좌우하는 매개변수를 자동 추정
        cand = [p for p in ("r_pin", "h_pin", "p", "n", "t_base") if p in r["parameters"]]
        if cand:
            pj["param_names"] = [c for c in cand if c in ("r_pin", "p", "n")] or cand
        pj_path.write_text(json.dumps(pj, ensure_ascii=False, indent=2))
        print(f"\n판정: 파라메트릭 - 자동화 가능")
        print(f"   project.json 갱신: source_mph, study_tag={pj.get('study_tag')}, "
              f"param_names={pj.get('param_names')}")

    print()
    return status()


if __name__ == "__main__":
    sys.exit(main())
