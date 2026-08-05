# 세대 저장소 - 구조/재료를 바꾼 후보마다 증거와 함께 보존하고 계보를 추적한다
"""
fbuf 골든 계보 규칙을 COMSOL 쪽으로 옮긴 것.

원칙 3가지:
  1. 세대는 불변이다. 한 번 쓰면 고치지 않는다 (재현성).
  2. 메시 수렴 게이트를 통과하지 못한 세대는 INVALID 로 남기되 지우지 않는다.
     - 실패도 계보의 일부다. 같은 실패를 다음 세션이 반복하지 않게 한다.
  3. 골든 승격은 코드가 하지 않는다. 사용자 확인 사항이다.

세대 폴더 구성:
  params.json     구조 + 재료 전체 (재현에 필요한 모든 것)
  mesh_gate.json  수렴 게이트 증거 (통과 여부 + 각 단계 수치)
  result.json     물리 결과
  report.md       무엇을 왜 바꿨나 (사람이 읽는 것)
  parent          부모 세대 이름 (계보)
"""

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import workspace as ws

ROOT = ws.WS
GEN_DIR = ws.WS / "generations"
GOLDEN = ws.WS / "golden"


def _slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(s))


def next_id() -> int:
    GEN_DIR.mkdir(exist_ok=True)
    ids = []
    for p in GEN_DIR.iterdir():
        if p.is_dir() and p.name.startswith("G") and p.name[1:4].isdigit():
            ids.append(int(p.name[1:4]))
    return max(ids) + 1 if ids else 0


def save(label, params, result, mesh_gate, changed, rationale,
         parent=None, materials=None):
    """세대를 기록한다.

    label      짧은 이름 (예: "rpin115")
    params     Params 데이터클래스 또는 dict
    result     solve_case 결과 (T 필드는 제외하고 저장)
    mesh_gate  {"passed": bool, "steps": [...], "criterion": "..."}
    changed    부모 대비 바뀐 것 {"r_pin": (75e-6, 115e-6), ...}
    rationale  왜 이걸 바꿨나 (한 문장)
    parent     부모 세대 폴더명
    """
    gid = next_id()
    name = f"G{gid:03d}_{_slug(label)}"
    d = GEN_DIR / name
    d.mkdir(parents=True, exist_ok=False)

    pdict = asdict(params) if hasattr(params, "__dataclass_fields__") else dict(params)
    # 파생 속성도 함께 남긴다 (재현 시 검산용)
    for attr in ("z_hs", "x0", "y0"):
        if hasattr(params, attr):
            pdict[f"_{attr}"] = getattr(params, attr)
    if materials:
        pdict["_materials"] = materials

    (d / "params.json").write_text(json.dumps(pdict, indent=2, ensure_ascii=False))
    (d / "mesh_gate.json").write_text(json.dumps(mesh_gate, indent=2, ensure_ascii=False))
    (d / "result.json").write_text(json.dumps(
        {k: v for k, v in result.items() if k != "T"}, indent=2, ensure_ascii=False))
    if parent:
        (d / "parent").write_text(parent + "\n")

    valid = mesh_gate.get("passed", False)
    lines = [
        f"# {name}",
        "",
        f"상태: {'VALID' if valid else 'INVALID (메시 수렴 게이트 실패 - 결과 신뢰 불가)'}",
        f"부모: {parent or '(없음)'}",
        "",
        "## 왜 바꿨나",
        rationale or "(미기재)",
        "",
        "## 부모 대비 변경",
    ]
    if changed:
        lines.append("")
        lines.append("| 항목 | 부모 | 이 세대 |")
        lines.append("|---|---|---|")
        for k, (a, b) in changed.items():
            fa = f"{a*1e6:.1f} um" if isinstance(a, float) and abs(a) < 1 else a
            fb = f"{b*1e6:.1f} um" if isinstance(b, float) and abs(b) < 1 else b
            lines.append(f"| {k} | {fa} | {fb} |")
    else:
        lines.append("(없음 - 기준 세대)")
    lines += [
        "",
        "## 결과",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| R_th | {result.get('R_th', float('nan')):.5f} K/W |",
        f"| Q_conv | {result.get('Q_conv', float('nan')):.5f} W |",
        f"| T_max | {result.get('T_max', float('nan')):.3f} K |",
        f"| T_max_hs | {result.get('T_max_hs', float('nan')):.3f} K |",
        f"| A_conv | {result.get('A_conv', float('nan'))*1e6:.4f} mm^2 |",
        "",
        "## 메시 수렴 게이트",
        "",
        f"판정: {'PASS' if valid else 'FAIL'} — {mesh_gate.get('criterion', '')}",
    ]
    for s in mesh_gate.get("steps", []):
        lines.append(f"- hmax {s['hmax']*1e6:.0f} um: R_th={s['R_th']:.5f} "
                     f"nodes={s['nodes']}")
    (d / "report.md").write_text("\n".join(lines) + "\n")
    return name


def load(name):
    d = GEN_DIR / name
    out = {"name": name}
    for f, key in [("params.json", "params"), ("result.json", "result"),
                   ("mesh_gate.json", "mesh_gate")]:
        p = d / f
        out[key] = json.loads(p.read_text()) if p.exists() else {}
    pp = d / "parent"
    out["parent"] = pp.read_text().strip() if pp.exists() else None
    out["valid"] = out["mesh_gate"].get("passed", False)
    return out


def all_generations():
    if not GEN_DIR.exists():
        return []
    names = sorted(p.name for p in GEN_DIR.iterdir()
                   if p.is_dir() and p.name.startswith("G"))
    return [load(n) for n in names]


def current_golden():
    if GOLDEN.is_symlink():
        return os.readlink(GOLDEN).split("/")[-1]
    return None


def promote(name):
    """골든 승격. 사용자 확인 후에만 호출할 것 - 코드가 스스로 부르지 않는다."""
    g = load(name)
    if not g["valid"]:
        raise RuntimeError(f"{name} 은 메시 게이트를 통과하지 못했다 - 승격 불가")
    if GOLDEN.is_symlink() or GOLDEN.exists():
        GOLDEN.unlink()
    GOLDEN.symlink_to(Path("generations") / name)
    return name
