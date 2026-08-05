#!/usr/bin/env bash
# 플러그인 실행환경을 준비한다 - venv + 의존성 + 작업공간 초기화
#
# 다른 머신/다른 Claude Code 환경에서 처음 쓸 때 한 번만 실행한다.
# sudo 를 쓰지 않는다 (전부 사용자 로컬 venv).
#
# 사용:
#   bash bootstrap.sh                          현재 디렉터리에 작업공간 생성
#   bash bootstrap.sh --ws <경로>              작업공간 위치 지정
#   bash bootstrap.sh --source-mph <원본.mph>  원본 모델까지 등록

set -euo pipefail
PLUGIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$PLUGIN/app"
VENV="$PLUGIN/.venv"

WS_ARG=""; SRC_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ws) WS_ARG="$2"; shift 2 ;;
    --source-mph) SRC_ARG="$2"; shift 2 ;;
    *) echo "알 수 없는 인자: $1" >&2; exit 1 ;;
  esac
done

echo "플러그인: $PLUGIN"

# --- 1. venv ---
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "venv 생성중..."
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
echo "의존성 확인/설치중 (gmsh, meshio, scikit-fem, numpy, scipy)..."
"$VENV/bin/pip" install -q gmsh meshio scikit-fem numpy scipy

"$VENV/bin/python" - <<'PY'
import importlib
bad = []
for m in ("gmsh", "skfem", "meshio", "numpy", "scipy"):
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append(f"{m}: {e}")
if bad:
    raise SystemExit("의존성 실패:\n  " + "\n  ".join(bad))
import gmsh, skfem, numpy, scipy
print(f"  gmsh {gmsh.__version__}  skfem {skfem.__version__} "
      f"numpy {numpy.__version__}  scipy {scipy.__version__}")
PY

# --- 2. 작업공간 ---
export CHBM_WS="${WS_ARG:-$PWD/.comsol-hbm}"
"$VENV/bin/python" "$APP/init_ws.py" ${SRC_ARG:+--source-mph "$SRC_ARG"}

# --- 3. 자체 검증 게이트 ---
echo
echo "해석해 대조군 실행중 (솔버 검증)..."
CHBM_WS="$CHBM_WS" "$VENV/bin/python" "$APP/validate_analytic.py" 2>&1 | tail -3

cat <<EOF

준비 완료.
  작업공간 : $CHBM_WS
  파이썬   : $VENV/bin/python

앞으로 실행할 때:
  export CHBM_WS="$CHBM_WS"
  $VENV/bin/python $APP/<스크립트>.py

원본 모델을 아직 등록하지 않았다면:
  $VENV/bin/python $APP/init_ws.py --source-mph <원본.mph>
EOF
