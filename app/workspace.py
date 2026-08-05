# 플러그인 코드와 프로젝트 데이터를 분리한다 - 한 플러그인으로 여러 프로젝트를 다루기 위함
"""
플러그인 코드는 읽기 전용으로 한 곳에 있고, 프로젝트마다 다른 것(목표, 세대, 산출물)은
작업공간에 둔다.

작업공간 결정 순서:
  1. 환경변수 CHBM_WS
  2. 현재 디렉터리부터 위로 올라가며 .comsol-hbm/ 탐색
  3. 없으면 ./.comsol-hbm/ 를 새로 만든다

작업공간 구성:
  project.json    프로젝트 설정 (원본 .mph 경로, COMSOL 경로, 시스템 스펙)
  goal.json       탐색 목표 (목적함수, 범위, 제약, 모델 가정)
  generations/    세대 저장소
  runs/           중간 산출물 (메시 등, 재생성 가능)
  out/            최종 산출물 (.mph, 리포트)
"""

import json
import os
import shutil
from pathlib import Path

APP = Path(__file__).resolve().parent          # 플러그인 app/ (읽기 전용)
PLUGIN = APP.parent


def find_ws(start: Path | None = None) -> Path:
    env = os.environ.get("CHBM_WS")
    if env:
        return Path(env).expanduser().resolve()
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        cand = d / ".comsol-hbm"
        if cand.is_dir():
            return cand
    return (cur / ".comsol-hbm").resolve()


WS = find_ws()


def ensure(ws: Path | None = None) -> Path:
    """작업공간을 만들고 기본 설정 파일을 깔아둔다."""
    ws = ws or WS
    for sub in ("", "generations", "runs", "out"):
        (ws / sub).mkdir(parents=True, exist_ok=True)
    for name in ("goal.json", "project.json"):
        dst = ws / name
        if not dst.exists():
            src = APP / "templates" / name
            if src.exists():
                shutil.copy(src, dst)
    return ws


def path(*parts) -> Path:
    return WS.joinpath(*parts)


def _load(name, required=True):
    p = WS / name
    if not p.exists():
        if required:
            raise SystemExit(
                f"{name} 이 없다: {p}\n"
                f"작업공간을 초기화할 것: python {APP}/init_ws.py")
        return {}
    return json.loads(p.read_text())


def goal():
    return _load("goal.json")


def project():
    return _load("project.json")


def strip_comments(d: dict) -> dict:
    """'_' 로 시작하는 키는 설명 주석이다. 값으로 쓰지 않는다."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def apply_limits():
    """goal.json 의 limits 를 constraints 모듈에 반영한다."""
    import constraints as C
    lim = strip_comments(goal().get("limits", {}))
    if lim:
        C.set_limits(**lim)
    return lim


def comsol_cmd() -> str | None:
    """COMSOL 실행 스크립트를 찾는다. 없으면 None."""
    pj = project()
    for cand in [os.environ.get("COMSOL_CMD"), pj.get("comsol_cmd")]:
        if cand and Path(cand).exists():
            return cand
    root = os.environ.get("COMSOL_ROOT") or pj.get("comsol_root")
    if root:
        exe = Path(root) / "bin" / "comsol"
        if exe.exists():
            return str(exe)
    for g in ("/opt/comsol*/multiphysics/bin/comsol", "/usr/local/comsol*/multiphysics/bin/comsol"):
        hits = sorted(Path("/").glob(g.lstrip("/")))
        if hits:
            return str(hits[-1])
    return None


def source_mph() -> Path | None:
    p = project().get("source_mph")
    return Path(p) if p else None


def calibration() -> dict:
    return strip_comments(project().get("calibration", {}))


def base_params():
    """goal.json 의 모델 가정 + project.json 의 캘리브레이션을 반영한 기준 Params.

    탐색 스크립트는 반드시 이걸로 시작해야 한다. Params() 를 직접 쓰면
    캘리브레이션이 조용히 무시되어 미보정 결과가 나온다.
    """
    from params import Params
    apply_limits()
    g = goal()
    mo = strip_comments(g.get("model_options", {}))
    cal = calibration()
    kw = {}
    if "anisotropic_materials" in mo:
        kw["anisotropic"] = mo["anisotropic_materials"]
    for src, dst in (("hs_orientation", "hs_orientation"),
                     ("process_constraints", "process_constraints"),
                     ("h_model", "h_model"), ("coolant", "coolant"),
                     ("v_inf", "v_inf")):
        if src in mo:
            kw[dst] = mo[src]
    if mo.get("disabled_rules"):
        kw["disabled_rules"] = tuple(mo["disabled_rules"])
    if cal.get("p_pump"):
        kw["p_pump"] = cal["p_pump"]
    elif mo.get("p_pump"):
        kw["p_pump"] = mo["p_pump"]
    if cal.get("stack_resistance_factor") is not None:
        kw["stack_k_factor"] = cal["stack_resistance_factor"]
    return Params().with_(**kw)
