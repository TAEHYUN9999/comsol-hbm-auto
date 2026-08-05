# comsol-hbm-auto

자연어 목표 -> 오픈소스 대량 탐색 -> 판정 게이트 -> 골든 승격 -> COMSOL 배치 1회 -> **풀린 `.mph`**.

HBM 다이스택 + 핀 히트싱크 열저항 최적화용. 2026-08-05 실증 세션에서 555세대를 돌리고
COMSOL 배치까지 완주해 만든 것이다.

---

## 왜 이런 구조인가

**COMSOL 1케이스 = 약 10분(실측 570초). 오픈소스 백엔드 = 0.2~1.3초.**

555케이스를 COMSOL 로 돌리면 4일 이상 걸린다. 그래서 역할을 나눈다.

```
탐색 (수백~수천 케이스)   gmsh + scikit-fem      분 단위
확정 골든 1건 검증        COMSOL batch           10분
```

이 구조의 대가는 "빠른 모델이 COMSOL 과 얼마나 다른가"를 알아야 한다는 것이고,
그게 `calibrate.py` 가 존재하는 이유다.

---

## 설치

```bash
bash scripts/bootstrap.sh --source-mph <원본.mph>
```

sudo 를 쓰지 않는다. 플러그인 안에 venv 를 만들고 gmsh/meshio/scikit-fem/numpy/scipy 를 깐다.
원본 모델을 주면 **파라메트릭 여부를 자동 검사**한다 (CAD 임포트 형상이면 자동화 불가이므로
여기서 걸러낸다). 마지막에 해석해 대조군 게이트를 돌려 솔버가 정상인지 확인한다.

COMSOL 은 `COMSOL_ROOT` 환경변수나 `project.json` 의 `comsol_cmd` 로 지정한다.

---

## 사용

슬래시 커맨드:

```
/comsol-hbm 유로폭 70um 기준으로 최적 찾아서 mph 만들어라
```

직접 실행:

```bash
export CHBM_WS=<작업공간>
PY=<플러그인>/.venv/bin/python
APP=<플러그인>/app

$PY $APP/init_ws.py --status                  상태
$PY $APP/inspect_mph.py <파일.mph>            COMSOL 없이 모델 해부
$PY $APP/calibrate.py --show                  캘리브레이션 상태
$PY $APP/calibrate.py --tmin 313.13           COMSOL 기준값으로 보정
$PY $APP/explore.py --baseline                기준 세대
$PY $APP/explore.py --axis structure --h-model pumping_power --tag s1
$PY $APP/analyze_optimum.py --tag s1          발산/제약 판정 (1D)
$PY $APP/refine.py                            (r_pin,p) 2D 교차확인
$PY $APP/line_search.py                       제약선 탐색 + 스펙 민감도
$PY $APP/promote.py <세대>                    골든 승격 (사용자 확인)
$PY $APP/report.py                            history.html
bash <플러그인>/scripts/solve_comsol.sh --params r_pin=78[um],p=206[um],n=6
```

### 모델 가정 스위치 (Vivado impl 전략 고르듯)

```
--anisotropy on|off        이방성 재료를 이방성으로 풀 것인가
--constraints on|off       공정 제약 필터
--disable-rule <이름> ...  개별 규칙 해제
--h-model fixed|velocity|pumping_power
--coolant water|FC72|air  --p-pump <W>
```

스위치 상태는 세대마다 기록되어 히스토리에서 구분된다.

---

## 작업공간

플러그인 코드는 읽기 전용, 프로젝트 데이터는 작업공간에 둔다.
`CHBM_WS` 환경변수 또는 상위 디렉터리의 `.comsol-hbm/` 을 자동 탐색한다.

```
.comsol-hbm/
  project.json     경로/장비/캘리브레이션
  goal.json        목적함수/탐색범위/제약/모델가정
  generations/     세대 저장소 (불변, 실패도 보존)
  runs/            중간 산출물 (재생성 가능)
  out/             .mph, history.html, 로그
```

---

## 결과 보고 규칙 (중요)

**개선은 절대값(K/W)으로 보고한다.** 스택 저항은 모든 설계에 똑같이 붙는 직렬 항이라
히트싱크 개선의 절대량은 캘리브레이션과 무관하게 일정하다.

실측 예 (같은 설계쌍):

| 보정계수 | 기준 R_th | 후보 R_th | 백분율 | **절대차** |
|---|---|---|---|---|
| 1.0 (미보정) | 23.799 | 15.486 | -34.9% | **8.3125** |
| 0.131 (보정) | 56.930 | 48.618 | -14.6% | **8.3125** |

백분율은 2.4배 차이나지만 절대차는 소수점 4자리까지 동일하다.
캘리브레이션 전이면 "절대 개선 X K/W (백분율은 스택저항 확정 후)" 로 쓴다.

---

## 하드룰

1. **메시는 최적화 대상이 아니다.** 세대마다 수렴 게이트를 통과해야 비교가 공정하다.
2. **경계 비교에 허용오차 필수.** 최적해가 제약선 위를 미끄러져 관심 지점이 전부 경계에 놓인다.
   `constraints.TOL` / `params._TOL` 제거 금지. (실측: 1e-20 잔차가 후보 생사를 갈랐다)
3. **`hmin` 은 물리 제약이 아니다.** 원본 메시 설정에서 물려받은 수치 가드다.
4. **온도 기반 목적함수 금지.** 고정온도 경계 구동이라 `T_max` 가 묶인다. `rth`/`q_conv` 를 쓴다.
5. **`.mph` XML 직접 편집 금지.** `buildStatus` 가 갱신되지 않아 배치가 옛 형상을 푼다.
   반드시 `-pname/-plist` 주입.
6. **긴 작업은 배경 실행 + 완료 알림 재진입.** 성공 마커만 grep 하면 크래시를 못 잡는다.
7. **침묵은 진행중이 아니다.** 로그가 멈추면 프로세스 생존을 확인하라.

---

## 실패 사례 (전부 실측)

| 증상 | 원인 | 처방 |
|---|---|---|
| 배치가 옛 형상을 품 (8분 낭비) | XML 편집 -> buildStatus 미갱신 | `-pname/-plist` |
| 최적점이 항상 격자 끝 | 억제 제약 부재 | 실제 스펙을 `limits` 로 |
| 1D 게이트 INTERIOR 오판 | 결합 제약 `p-2r>=gap` | `refine.py` 2D |
| 후보가 이유 없이 탈락 | 부동소수점 경계 | `TOL` 가드 |
| 재료 최적이 비현실적 | 공정 제약 부재 | `constraints.py` |
| 절대값이 COMSOL 과 2.4배 차이 | 유효물성이 수축저항 무시 | `calibrate.py` |
| 캘리브레이션이 무시됨 | `Params()` 직접 생성 | `ws.base_params()` 사용 |

---

## 검증 상태

- 해석해 대조군 (Incropera 원통핀 엄밀해): 오차 **0.139%**
- 메시 수렴 게이트: 555세대 전부 통과
- `.mph` 파라미터 주입: 자유도 867,430 -> 884,367, 지오메트리 객체 5,695 -> 5,788 확인
- COMSOL 배치 완주: 570초, 709.8 MB 산출
- 캘리브레이션 기준값: **잠정** (원본 파일에 저장돼 있던 해의 T_min=313.13 K,
  출처 불명확). 새로 푼 파일에서 파생값을 재평가해 갱신할 것.

---

## 알려진 한계

- Zukauskas 상관식을 `Re_max` 5~30 구간에서 쓴다 (정의역 Re>=10, 마찰계수 Re>=1e3).
  경향은 견고하나 절대값은 CFD/실측 검증이 필요하다. 경고가 매 케이스 로그에 남는다.
- TSV/범프 5,696개를 층 단위 이방성으로 치환한다. `resolve_layers="full"` 로 차이를
  측정할 수 있으나 아직 안 했다.
- 구조해석 없음 (CTE 응력). 핀 Cu 질량이 늘어나는 설계를 낼 수 있다.
- 시스템 스펙 2개(`MIN_FLOW_GAP`, `MAX_PACKAGE_HEIGHT`)가 답을 좌우한다.
  실측: 유로폭 30~150um 구간에서 최적 R_th 가 84% 폭, 최적 핀수가 64->16 으로 변했다.
