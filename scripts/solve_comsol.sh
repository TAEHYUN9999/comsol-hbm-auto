#!/usr/bin/env bash
# 원본 .mph 에 매개변수를 실행시점 주입해 재빌드/재메시/재계산하고 풀린 .mph 를 낸다
#
# 왜 -pname/-plist 인가 (절대 바꾸지 마라):
#   .mph 안의 매개변수를 XML 로 직접 편집하면 COMSOL 은 그 변화를 모른다.
#   지오메트리 노드의 buildStatus 가 BUILT 로 남아 배치가 재빌드를 건너뛰고
#   옛 형상을 그냥 푼다. 실측(2026-08-05): 자유도가 옛 값 그대로 나왔고 8분이 낭비됐다.
#   -pname/-plist 는 의존성 추적을 작동시켜 지오메트리 -> 메시 -> 해 를 다시 만든다.
#
# 사용:
#   solve_comsol.sh --params r_pin=78[um],p=206[um],n=6
#   solve_comsol.sh --params ... --out <출력.mph> --source <원본.mph>
#
# 설정은 작업공간 project.json 에서 읽는다 (source_mph, comsol_cmd, study_tag, np).

set -uo pipefail
PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$PLUGIN/app"
PY="${CHBM_PYTHON:-${CHBM_VENV:-$PLUGIN/.venv}/bin/python}"

PARAMS=""; OUT=""; SRC=""; TAG=""; LOWMEM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --params) PARAMS="$2"; shift 2 ;;
    --out)    OUT="$2"; shift 2 ;;
    --source) SRC="$2"; shift 2 ;;
    --tag)    TAG="$2"; shift 2 ;;
    --lowmem) LOWMEM=1; shift ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 1 ;;
  esac
done
[[ -n "$PARAMS" ]] || { echo "오류: --params 필수 (예: r_pin=78[um],p=206[um],n=6)" >&2; exit 1; }

# project.json 에서 설정을 읽는다
eval "$("$PY" - <<'PY'
import sys, shlex
from pathlib import Path
sys.path.insert(0, __import__('os').environ.get('CHBM_APP', ''))
import workspace as ws
pj = ws.project()
def emit(k, v): print(f"{k}={shlex.quote(str(v or ''))}")
emit("CFG_SRC", pj.get("source_mph"))
emit("CFG_CMD", ws.comsol_cmd())
emit("CFG_STUDY", pj.get("study_tag") or "std1")
emit("CFG_NP", pj.get("np") or "")
emit("CFG_WS", ws.WS)
PY
)"

SRC="${SRC:-$CFG_SRC}"
COMSOL="$CFG_CMD"
STUDY="$CFG_STUDY"
NP="${NP:-${CFG_NP:-$(( $(nproc) > 32 ? 32 : $(nproc) ))}}"
SLUG="$(echo "$PARAMS" | tr -cd 'A-Za-z0-9=,._-' | tr '=,' '__' | cut -c1-60)"
OUT="${OUT:-$CFG_WS/out/solved_${TAG:-$SLUG}.mph}"
LOG="$CFG_WS/out/solve_$(date +%Y%m%d_%H%M%S).log"

[[ -n "$COMSOL" && -f "$COMSOL" ]] || { echo "오류: COMSOL 실행파일을 찾을 수 없다. COMSOL_ROOT 또는 project.json comsol_cmd 설정." >&2; exit 1; }
[[ -f "$SRC" ]] || { echo "오류: 원본 mph 없음: $SRC" >&2; exit 1; }

# 저메모리(노트북) 모드: 이산화 2차 -> 1차 변형본을 만들어 그것을 입력으로 쓴다.
# 자유도가 약 7.5배 줄어 메모리가 16.5GB 급에서 1~2GB 급으로 내려간다.
if [[ $LOWMEM -eq 1 ]]; then
  LM="$CFG_WS/out/lowmem_source.mph"
  if [[ ! -f "$LM" ]]; then
    echo "저메모리 변형본 생성중 (이산화 2차 -> 1차)..."
    CHBM_APP="$APP" "$PY" "$APP/make_lowmem.py" "$SRC" "$LM" | tail -4 || exit 1
  else
    echo "저메모리 변형본 재사용: $LM"
  fi
  SRC="$LM"
fi
[[ -e "$OUT" ]] && { echo "오류: 출력이 이미 있다(덮어쓰지 않음): $OUT" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

PNAME="$(echo "$PARAMS" | tr ',' '\n' | cut -d= -f1 | paste -sd,)"
PLIST="$(echo "$PARAMS" | tr ',' '\n' | cut -d= -f2- | paste -sd,)"

echo "원본   : $SRC"
echo "출력   : $OUT"
echo "로그   : $LOG"
echo "주입   : $PNAME = $PLIST"
echo "스터디 : $STUDY   코어: $NP"
echo "시작   : $(date '+%F %T')"
echo
echo "지오메트리 재빌드 -> 재메시 -> 해석 순으로 진행된다."
echo

"$COMSOL" batch -inputfile "$SRC" -outputfile "$OUT" -batchlog "$LOG" \
  -study "$STUDY" -pname "$PNAME" -plist "$PLIST" -np "$NP" -recover
rc=$?
echo
echo "종료 : $(date '+%F %T')  (exit=$rc)"

fail=0
if [[ -f "$LOG" ]]; then
  if grep -qiE 'license|out of memory|could not obtain|exception|error:' "$LOG"; then
    echo; echo "--- 실패 시그니처 ---"
    grep -inE 'license|out of memory|could not obtain|exception|error:' "$LOG" | head -15
    fail=1
  fi
  if [[ $LOWMEM -eq 1 ]]; then
    echo; echo "--- 저메모리 모드 반영 확인 ---"
    dof=$(grep -oE '자유도 수: [0-9]+' "$LOG" | head -1 | grep -oE '[0-9]+')
    if [[ -n "$dof" ]]; then
      echo "  자유도 $dof"
      [[ "$dof" -lt 400000 ]] \
        && echo "  -> 1차 이산화 반영됨 (2차 대비 크게 감소)" \
        || { echo "  경고: 자유도가 줄지 않았다. 이산화 변경이 무시된 것이다."; \
             echo "        GUI 에서 물리현상 > 이산화 > 온도: 선형 으로 직접 바꿀 것."; fail=1; }
    fi
  fi
  echo; echo "--- 재빌드 확인 ---"
  if grep -qiE '요소 수|Number of elements|자유 메시|Free mesh|사면체' "$LOG"; then
    grep -inE '요소 수|Number of elements|자유 메시|최소 요소 품질|자유도|degrees of freedom' "$LOG" | head -8
  else
    echo "경고: 메시 재생성 로그가 없다. 옛 형상으로 풀렸을 수 있다."
    grep -inE '자유도|degrees of freedom' "$LOG" | head -3
    fail=1
  fi
fi

if [[ ! -f "$OUT" ]]; then
  echo "실패: 출력 파일이 없다 (조용한 실패). 로그: $LOG" >&2
  exit 3
fi

echo; echo "출력 크기: $(du -h "$OUT" | cut -f1)"
echo "--- 산출물 매개변수 최종 확인 ---"
CHBM_APP="$APP" "$PY" "$APP/inspect_mph.py" "$OUT" 2>/dev/null \
  | sed -n '/전역 매개변수/,/^$/p' | head -22

[[ $fail -eq 0 ]] || { echo; echo "경고가 있었다. 위 내용을 확인할 것." >&2; exit 4; }
echo; echo "완료."
