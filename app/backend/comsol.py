# COMSOL 백엔드 - 원본 .mph 를 파라메트릭 배치로 돌리고 파생값을 회수한다
"""
skfem 백엔드와 동일한 인터페이스를 제공하므로 sweep.py 는 어느 쪽인지 모른다.

주의 - 실행 요건:
  이 모듈은 '정품 라이선스가 설정된 COMSOL 설치'를 전제로 한다.
  COMSOL_ROOT 환경변수 또는 comsol_root 인자로 설치 경로를 지정한다.
  라이선스가 유효하지 않으면 comsol batch 가 체크아웃 단계에서 실패하며,
  그 오류는 그대로 위로 전달된다.

동작 방식:
  comsol batch -inputfile <mph> -pname r_pin,h_pin -plist "75[um],300[um]"
               -methodcall ... -outputfile <out.mph> -batchlog <log>
  그 뒤 -nosave 대신 파생값을 텍스트로 뽑기 위해 Export/Table 노드를 쓴다.

원본 모델에는 파생값 max1/max2(MaxVolume, 표현식 T)가 이미 있으므로
그 결과를 표로 내보내는 Export 노드 하나만 추가하면 된다. 그 추가 작업은
GUI 또는 아래 build_export_method() 가 내는 Java 메서드로 한 번만 하면 된다.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from params import Params  # noqa: E402


class ComsolNotConfigured(RuntimeError):
    pass


def find_comsol(comsol_root: str | None = None) -> str:
    root = comsol_root or os.environ.get("COMSOL_ROOT")
    if not root:
        raise ComsolNotConfigured(
            "COMSOL_ROOT 가 설정되지 않았다. 예: export COMSOL_ROOT=/opt/comsol56/multiphysics")
    exe = Path(root) / "bin" / "comsol"
    if not exe.exists():
        raise ComsolNotConfigured(f"comsol 실행파일이 없다: {exe}")
    return str(exe)


# 원본 모델의 파라미터 이름 -> Params 필드 이름
PNAME = {
    "r_pin": "r_pin",
    "h_pin": "h_pin",
    "t_base": "t_base",
    "p": "p",
    "n": "n",
}


def _plist(pm: Params, names):
    """COMSOL -plist 문자열. 길이 파라미터는 [m] 단위를 명시한다."""
    out = []
    for nm in names:
        v = getattr(pm, PNAME[nm])
        out.append(str(int(v)) if nm == "n" else f"{v:.9g}[m]")
    return out


def solve_case(mph_in: str, pm: Params, names, outdir: str,
               comsol_root: str | None = None, ncpu: int | None = None,
               timeout: int = 7200):
    """단일 케이스를 comsol batch 로 푼다.

    반환: dict(T_max=..., raw_table=..., log=...)
    라이선스/솔버 실패는 예외로 올린다 - 조용한 실패를 만들지 않는다.
    """
    exe = find_comsol(comsol_root)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_mph = outdir / "out.mph"
    log = outdir / "batch.log"
    table = outdir / "derived.txt"

    cmd = [exe, "batch",
           "-inputfile", str(mph_in),
           "-outputfile", str(out_mph),
           "-batchlog", str(log),
           "-pname", ",".join(names),
           "-plist", ",".join(_plist(pm, names)),
           "-study", "std1"]
    if ncpu:
        cmd += ["-np", str(ncpu)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    logtext = log.read_text(errors="replace") if log.exists() else ""
    blob = proc.stdout + proc.stderr + logtext

    # 조용한 실패 방지: 성공 마커가 아니라 실패 시그니처를 먼저 본다
    for sig in ["License error", "Could not obtain license", "LICENSE",
                "Out of memory", "Failed to", "Error:"]:
        if sig.lower() in blob.lower():
            raise RuntimeError(f"COMSOL batch 실패 ({sig}):\n{blob[-2000:]}")
    if proc.returncode != 0:
        raise RuntimeError(f"COMSOL batch 종료코드 {proc.returncode}:\n{blob[-2000:]}")
    if not out_mph.exists():
        raise RuntimeError(f"출력 mph 가 생성되지 않았다: {out_mph}\n{blob[-2000:]}")

    result = {"log": logtext, "out_mph": str(out_mph)}
    if table.exists():
        result["raw_table"] = table.read_text(errors="replace")
        result.update(_parse_table(result["raw_table"]))
    return result


def _parse_table(text: str) -> dict:
    """Export/Table 텍스트에서 마지막 수치 행을 뽑는다."""
    rows = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("%")]
    if not rows:
        return {}
    vals = [float(x) for x in re.findall(r"[-+0-9.eE]+", rows[-1])]
    out = {}
    if vals:
        out["T_max"] = vals[-1]
    return out


def build_export_method() -> str:
    """원본 .mph 에 파생값 내보내기 노드를 한 번만 추가하기 위한 Java 메서드.

    COMSOL GUI 의 Application Builder > Method 에 붙여 1회 실행하거나,
    Model Method 로 저장해 batch 에서 -methodcall 로 부른다.
    """
    return """
// 파생값(max1, max2)을 텍스트 표로 내보내는 노드를 추가한다. 1회만 실행하면 된다.
model.result().numerical("max1").set("table", "tbl1");
model.result().table().create("tbl1", "Table");
model.result().numerical("max1").setResult();
model.result().export().create("tblexp1", "Table");
model.result().export("tblexp1").set("table", "tbl1");
model.result().export("tblexp1").set("filename", "derived.txt");
model.result().export("tblexp1").run();
"""


if __name__ == "__main__":
    try:
        print("COMSOL 실행파일:", find_comsol())
    except ComsolNotConfigured as e:
        print("미설정:", e)
        print("\n이 백엔드는 정품 라이선스가 설정된 COMSOL 에서만 동작한다.")
