---
name: comsol-hbm
description: Use when optimizing a parametric COMSOL heat-transfer model (HBM 다이스택 + 핀 히트싱크 계보) from a natural-language goal and delivering a solved .mph — 텍스트로 목표 주면 탐색·판정·골든승격·mph 산출까지. 트리거는 "핀 최적화", "열저항 줄여라", "mph로 결과 내라", "골든 갱신", "유로폭/패키지높이 스펙 바꿔서 다시", "COMSOL 자동화". NOT for non-parametric CAD-import models (inspect_mph.py 가 먼저 걸러낸다).
---

# COMSOL HBM 핀히트싱크 자율 최적화

자연어 목표 -> 오픈소스 대량 탐색 -> 판정 게이트 -> 골든 승격 -> COMSOL 배치 1회 -> 풀린 `.mph`.

## 핵심 전제 (이걸 어기면 결과가 조용히 틀린다)

**COMSOL 1케이스는 약 10분, 오픈소스 백엔드는 0.2~1.3초다.** 그래서 역할을 나눈다.
탐색은 전부 오픈소스로 돌리고, COMSOL 은 확정된 골든 1건만 검증한다.
탐색을 COMSOL 로 돌리려 하지 마라 — 555케이스면 4일 이상 걸린다.

그 대가로 **오픈소스 모델이 COMSOL 과 얼마나 다른지를 반드시 알아야 한다.**
그게 `calibrate.py` 가 있는 이유다. 캘리브레이션 없는 절대값은 보고하지 마라.

## 절차

작업공간을 먼저 확인한다: `python $APP/init_ws.py --status`

### 0. 캘리브레이션 상태 확인 (건너뛰지 마라)

```bash
python $APP/calibrate.py --show
```

`stack_resistance_factor` 가 없거나 기준값이 비어 있으면 **절대값은 미검증이다.**
그 상태로도 탐색은 할 수 있지만, 보고할 때 반드시 아래 규칙을 지킨다.

**보고 규칙 (중요):**
- 개선을 **절대값(K/W)** 으로 보고하라. 스택 저항은 모든 설계에 똑같이 붙는 직렬 항이라
  히트싱크 개선의 절대량은 캘리브레이션과 무관하게 일정하다.
- **백분율은 캘리브레이션에 따라 크게 변한다.** 실측 사례: 같은 설계쌍이
  보정 전 -34.9%, 보정 후 -14.6% (절대차는 양쪽 모두 정확히 8.3125 K/W).
- 캘리브레이션 전이면 "절대 개선 X K/W (백분율은 스택저항 확정 후)" 로 쓴다.

### 1. 목표를 goal.json 으로 번역

사용자 지시에서 아래를 뽑아 `$WS/goal.json` 을 고친다.
- 목적함수 (`objective`) — 기본 `rth`
- 탐색 범위 (`search.structure`, `search.materials`)
- 시스템 스펙 (`limits`) — 특히 `MIN_FLOW_GAP`, `MAX_PACKAGE_HEIGHT`
- 모델 가정 (`model_options`) — 이방성/공정제약/h모델

**`_` 로 시작하는 키는 주석이다. 값으로 쓰지 마라.**

### 2. 탐색

```bash
python $APP/explore.py --baseline                      # 기준 세대가 없을 때만
python $APP/explore.py --axis structure --h-model pumping_power --tag <태그>
python $APP/explore.py --axis materials --tag <태그>
```

케이스가 많으면 `run_in_background: true` 로 띄우고 **완료 알림으로 재진입**하라.
걸어놓고 턴을 닫지 마라.

### 3. 판정 게이트 (2단계. 1단계만 믿지 마라)

```bash
python $APP/analyze_optimum.py --tag <태그>
```

- `DIVERGENT` — 최적점이 격자 인공물에 고착. **모델링 실패다.** 그 변수를 억제하는
  실제 제약(공정/패키지/유동)을 찾아 `limits` 에 넣고 재탐색하라. 범위만 넓히는 것은 답이 아니다.
- `BOUNDED` — 모든 경계가 실제 제약. 여기서 멈추지 말고 4단계로 간다.

```bash
python $APP/refine.py          # (r_pin, p) 평면 2D 절단면
```

**`analyze_optimum` 은 변수를 1D 로만 본다.** `flow_gap` 은 `p - 2*r_pin >= gap` 으로
두 변수를 묶으므로, 제약선 위의 점이 각 투영에서 "내부 극값"으로 보인다.
`refine.py` 가 `CONSTRAINT-RIDING` 을 내면 최적은 격자가 아니라 **제약선 위**에 있다.

### 4. 제약선 탐색 + 스펙 민감도

```bash
python $APP/line_search.py
```

제약선을 따라 최적을 찾고, `MIN_FLOW_GAP` 을 바꿔가며 답이 얼마나 흔들리는지 낸다.
실측 사례: 30~150 um 구간에서 R_th 가 84% 폭으로 변했고 최적 핀수가 64 -> 16 으로 4배 차이났다.
**이 스펙이 확정되지 않으면 형상도 확정할 수 없다** — 사용자에게 그렇게 보고하라.

### 5. 골든 승격 (사용자 확인 사항)

```bash
python $APP/promote.py                    # 후보 목록
python $APP/promote.py <세대이름>         # 승격
```

**자동으로 승격하지 마라.** 사용자가 명시적으로 지시할 때만 한다.

### 6. .mph 산출

**RAM 이 16GB 급이면 `--lowmem` 을 붙인다.** 2차 이산화 기준 실측 메모리가 16.5 GB 라
그대로는 들어가지 않는다. `--lowmem` 은 이산화를 1차로 낮춘 변형본을 만들어 쓰며
자유도가 약 7.5배 줄어든다. 반영 여부는 스크립트가 자유도로 자동 대조하고,
무시됐으면 경고 후 `exit 4` 한다 (그때는 GUI 에서 이산화를 직접 바꿔야 한다).
탐색 루프 자체는 651 MB 이하라 저사양에서도 그대로 돌린다.

```bash
bash $PLUGIN/scripts/solve_comsol.sh --params r_pin=78[um],p=206[um],n=6
```

**반드시 `-pname/-plist` 주입 방식을 쓴다.** `.mph` 의 XML 을 직접 편집하면
지오메트리 `buildStatus` 가 `BUILT` 로 남아 배치가 **재빌드를 건너뛰고 옛 형상을 그냥 푼다.**
(실측: 자유도가 옛 값 그대로 나오고 8분이 낭비됐다)

입력은 편집본이 아니라 **원본 `.mph`** 를 쓴다. 원본은 절대 수정하지 않는다.

### 7. 산출물 검증 (자동)

스크립트가 아래를 검사하고 실패하면 알린다.
- 재빌드 로그 존재 여부 (없으면 옛 형상을 푼 것)
- 자유도가 기준값과 다른지
- 실패 시그니처 (라이선스/메모리/예외)
- 출력 파일 생성 여부 (exit 0 인데 산출물 없는 조용한 실패 방지)

그 뒤 `inspect_mph.py <출력.mph>` 로 매개변수가 실제 반영됐는지 최종 확인하라.

### 8. 리포트

```bash
python $APP/report.py       # $WS/out/history.html
```

## 하드룰

1. **메시는 최적화 대상이 아니다.** 세대마다 수렴 게이트를 통과해야 세대 간 비교가 공정하다.
   메시를 목적함수 기준으로 고르는 것은 수치 오차를 유리하게 고르는 것이다.
2. **경계 비교에는 허용오차가 필수다.** 최적해가 제약선 위를 미끄러지므로 관심 지점이
   전부 경계에 정확히 놓인다. `constraints.TOL` / `params._TOL` 가드를 제거하지 마라.
   (실측: 1e-20 잔차가 후보의 생사를 갈라 결과가 오염됐다)
3. **`hmin` 은 물리 제약이 아니다.** 원본 메시 설정에서 물려받은 수치 가드다.
   이게 `r_pin` 하한을 만들어 탐색을 막을 수 있다. 실제 하한은 `MIN_PIN_DIAMETER`.
4. **온도 기반 목적함수를 쓰지 마라.** 이 계보의 모델은 열원 없이 고정온도 경계로 구동되어
   `T_max` 가 경계값에 묶인다. 전 케이스 동일값이 나온다. `rth` 또는 `q_conv` 를 쓴다.
5. **긴 작업은 `run_in_background: true` 로 띄워 완료 알림으로 재진입하라.**
   성공 마커만 grep 하면 크래시와 진행중을 구분할 수 없다. 실패 시그니처를 함께 본다.
6. **침묵은 진행중이 아니다.** 로그가 멈추면 프로세스 생존을 확인하라.
   (실측: 선정 업데이트 단계가 6분간 조용하지만 CPU 2500% 로 정상 동작 중이었다)

## 실패 사례 (같은 함정을 반복하지 마라)

| 증상 | 원인 | 처방 |
|---|---|---|
| 배치가 옛 형상을 품 | XML 직접 편집 -> buildStatus 미갱신 | `-pname/-plist` 주입 |
| 최적점이 항상 격자 끝 | 그 변수를 억제하는 제약 부재 | 실제 스펙 찾아 `limits` 에 |
| 1D 게이트가 INTERIOR 오판 | 결합 제약(`flow_gap`) | `refine.py` 2D 교차확인 |
| 후보가 이유 없이 탈락 | 부동소수점 경계 비교 | `TOL` 가드 |
| 재료 최적이 비현실적 | 공정 제약 부재 | `constraints.py` 규칙 |
| 절대값이 COMSOL 과 크게 다름 | 유효물성이 수축저항 무시 | `calibrate.py` |

## 참고

- 모델 해부: `python $APP/inspect_mph.py <파일.mph>` — COMSOL 없이 매개변수/지오메트리
  파라메트릭 여부/재료/경계조건/스터디를 뽑는다. **파라메트릭이 아니면 자동화 불가**이므로
  새 모델을 받으면 이걸 먼저 돌려라.
- 검증 게이트: `validate_analytic.py` (해석해 대조, 실측 오차 0.139%),
  `validate_mesh.py` (메시 수렴)
- 상세 소견: `$PLUGIN/docs/findings.md`, `$PLUGIN/docs/conclusion.md`
