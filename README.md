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

## 설치 (다른 컴퓨터에서 처음 쓸 때)

### 사전 요구

```bash
# 1) 파이썬 3.10 이상 + venv
python3 --version
python3 -m venv --help        # 오류가 나면:
sudo apt install python3-venv

# 2) GitHub CLI (private 리포라 필수)
gh --version                  # 없으면:
sudo apt install gh
gh auth login                 # GitHub.com -> HTTPS -> 브라우저 인증
```

`gh auth login` 은 **머신당 한 번**이면 된다. 이후 `/plugin install` 과
`/plugin update` 에서 다시 묻지 않는다. WSL 에서도 동작한다(브라우저는 윈도우 쪽이 열린다).

Ubuntu 22.04 의 apt `gh` 는 2.4.0 으로 다소 낡았지만 인증과 플러그인 설치에는 충분하다.
최신판이 필요하면 GitHub 공식 저장소를 추가한다:

```bash
(type -p wget >/dev/null || sudo apt install wget -y) \
 && sudo mkdir -p -m 755 /etc/apt/keyrings \
 && wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
 && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
 && sudo apt update && sudo apt install gh -y
```

**COMSOL** 은 정품 라이선스가 설정된 설치본이 있어야 한다.
탐색·분석은 COMSOL 없이도 전부 되고, `.mph` 산출 단계에서만 필요하다.
`bootstrap.sh` 는 COMSOL 이 없어도 완주하며 `init_ws.py --status` 에 "못 찾음" 으로 표시된다.

### 1. 플러그인 설치 (Claude Code 안에서)

```
/plugin marketplace add TAEHYUN9999/comsol-hbm-auto
/plugin install comsol-hbm-auto@comsol-hbm-auto
```

설치되면 `~/.claude/plugins/cache/comsol-hbm-auto/comsol-hbm-auto/<버전>/` 에 들어간다.

### 2. 실행환경 부트스트랩 (터미널에서 한 번)

```bash
# 플러그인 경로를 잡는다 (버전 폴더가 바뀌어도 최신을 고른다)
PLUGIN=$(ls -d ~/.claude/plugins/cache/comsol-hbm-auto/comsol-hbm-auto/*/ | sort -V | tail -1)

# venv 는 캐시 밖에 둔다. 플러그인 업데이트 시 캐시가 지워져도 살아남는다.
export CHBM_VENV=~/.comsol-hbm-venv

cd <작업할 프로젝트 폴더>
bash "$PLUGIN/scripts/bootstrap.sh" --source-mph "<원본.mph>"
```

sudo 를 쓰지 않는다. venv 를 만들고 gmsh/meshio/scikit-fem/numpy/scipy 를 깐다.
원본 모델을 주면 **파라메트릭 여부를 자동 검사**한다 (CAD 임포트 형상이면 자동화 불가이므로
여기서 걸러낸다). 마지막에 해석해 대조군 게이트를 돌려 솔버가 정상인지 확인한다.

### 3. 환경변수 고정 (셸 프로필에 넣어두면 편하다)

```bash
export CHBM_VENV=~/.comsol-hbm-venv
export CHBM_WS=<작업폴더>/.comsol-hbm
export COMSOL_ROOT=/opt/comsol62/multiphysics     # 또는 project.json 의 comsol_cmd
```

`CHBM_WS` 를 안 넣어도 현재 디렉터리부터 위로 올라가며 `.comsol-hbm/` 을 자동 탐색한다.

### 4. 확인

```bash
$CHBM_VENV/bin/python "$PLUGIN/app/init_ws.py" --status
```

원본 mph 경로, COMSOL 탐지 여부, 캘리브레이션 상태, 세대 수가 나온다.

### 플러그인 업데이트 후

```
/plugin update comsol-hbm-auto
```

캐시 폴더가 새 버전으로 바뀌므로 `PLUGIN` 경로를 다시 잡는다.
`CHBM_VENV` 를 캐시 밖에 뒀다면 venv 재설치는 필요 없다. 그래도 한 번 더 돌리면
의존성만 확인하고 넘어간다 (idempotent).

### 어느 경로를 택할 것인가

| | 1~4번 (`/plugin install`) | 아래 클론 방식 |
|---|---|---|
| 목적 | **플러그인을 쓴다** | **플러그인 코드를 고친다** |
| `/comsol-hbm` 슬래시 커맨드 | O | **X** |
| SKILL.md 가 Claude Code 에 로드됨 | O | **X** |
| 말로 지시하면 알아서 진행 | O | **X** (스크립트를 직접 쳐야 함) |
| 스크립트 수동 실행 | O | O |

**처음 쓰는 컴퓨터라면 1~4번을 하라.** 아래 클론 방식만 하면 Claude Code 는 그 폴더의
존재를 모르므로 스킬도 커맨드도 뜨지 않는다.

### 플러그인 코드를 고칠 때 (개발자용)

```bash
git clone git@github.com:TAEHYUN9999/comsol-hbm-auto.git
cd comsol-hbm-auto
bash scripts/bootstrap.sh --source-mph <원본.mph>
```

고친 것을 Claude Code 에서 스킬로 쓰려면 클론 폴더를 마켓플레이스로 등록한다:

```
/plugin marketplace add <클론경로>
/plugin install comsol-hbm-auto@comsol-hbm-auto
/reload-plugins
```

이러면 GitHub 를 거치지 않고 로컬 수정본이 바로 스킬로 로드된다.

---

## 사용

슬래시 커맨드:

```
/comsol-hbm 유로폭 70um 기준으로 최적 찾아서 mph 만들어라
```

직접 실행:

```bash
PLUGIN=$(ls -d ~/.claude/plugins/cache/comsol-hbm-auto/comsol-hbm-auto/*/ | sort -V | tail -1)
PY=$CHBM_VENV/bin/python
APP=$PLUGIN/app

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
bash $PLUGIN/scripts/solve_comsol.sh --params r_pin=78[um],p=206[um],n=6
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

## 노트북 / 저사양 환경 (RAM 16GB, WSL2)

### 무엇이 무겁고 무엇이 가벼운가 (전부 실측)

| 작업 | 메모리 | 시간 | 16GB 노트북 |
|---|---|---|---|
| 탐색 1케이스 (일반) | **162 MB** | 1.0초 | 여유 |
| 탐색 1케이스 (10x10=100핀, 52k 절점) | **651 MB** | 10.2초 | 여유 |
| COMSOL 검증 (2차 이산화, 자유도 884,367) | **16.5 GB** | 570초 | **불가** |
| COMSOL 검증 (1차 이산화, 자유도 약 118,000) | 1~2 GB 추정 | 미측정 | 가능 |

**탐색 루프는 노트북에서 전혀 문제가 없다.** 555세대를 그대로 돌릴 수 있다.
무거운 것은 COMSOL 검증 1회뿐이다.

### 저메모리 모드

```bash
bash $PLUGIN/scripts/solve_comsol.sh --lowmem --params r_pin=78[um],p=206[um],n=6
```

이산화 차수를 2차에서 1차로 낮춘 변형본(`out/lowmem_source.mph`)을 자동 생성해 쓴다.
사면체 P2 는 P1 대비 자유도가 약 7.5배라, 낮추면 자유도가 884,367 -> 약 118,000 이 된다.
3D 직접 솔버 메모리는 자유도에 초선형으로 붙으므로 16.5 GB 급에서 1~2 GB 급으로 내려간다.

**반영 여부는 스크립트가 자동으로 확인한다.** 로그의 자유도가 40만 미만이면 반영된 것이고,
884,367 그대로면 무시된 것이라 경고하고 `exit 4` 한다. 그 경우 GUI 에서
`물리현상 > 이산화 > 온도: 선형` 으로 직접 바꿀 것.

변형본은 `make_lowmem.py` 가 만들며 **`order_temperature` 가 '2' 인 항목만** 치환한다
(이미 '1' 인 항목은 건드리지 않는다). 나머지 ZIP 엔트리는 원본과 바이트 동일함을 검증했다.

### 정확도 주의

P1 은 같은 메시에서 P2 보다 부정확하다. 정상상태 열전도는 해가 매끄러워 대개 충분하지만
**가정하지 말고 메시 수렴 게이트로 확인할 것.** 부족하면 메시를 조밀하게 해서 보상한다.
최종 확정값은 여유 있는 장비에서 2차 이산화로 한 번 더 돌리는 것이 안전하다.

### WSL2 설정

`%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=12GB
processors=8
swap=32GB
```

호스트 OS 에 4GB 를 남긴다. swap 을 크게 잡으면 2차 이산화로도 돌지만 스와핑으로
수 시간 걸릴 수 있어 저메모리 모드가 낫다.

**압축 해제는 반드시 리눅스 홈(`~/`)에.** `/mnt/c/...` 는 NTFS 경유라 I/O 가 수 배 느리고
권한 모델이 달라 실행 비트가 깨진다. 그리고 zip 대신 **tar** 를 쓸 것 (권한/심링크 보존).

---

## 다른 컴퓨터로 프로젝트를 통째로 옮기기

**리포에는 도구만 있다. 프로젝트 데이터는 따라가지 않는다.**

| | 리포 포함 | 크기 | 옮기는 법 |
|---|---|---|---|
| 스킬/앱/스크립트/문서 | O | 수백 KB | `/plugin install` |
| 작업공간 (세대, 골든, 캘리브레이션, goal.json) | X | 수십 MB | 아래 절차 |
| 원본 `.mph` | X | 수백 MB | 별도 복사 |
| 메시·중간 산출물 (`runs/`) | X | — | 재생성되므로 옮기지 않는다 |

원본 `.mph` 와 메시를 리포에 넣지 않는 것은 의도한 것이다. 하지만 **세대 이력과
캘리브레이션은 작고 가치가 크므로 반드시 함께 옮겨야 한다** — 없으면 골든도
보정계수도 잃고 처음부터 다시 시작하게 된다.

### 내보내기 (원래 컴퓨터)

```bash
cd <작업폴더>
tar czf comsol-hbm-ws.tar.gz --exclude='runs' .comsol-hbm
```

`tar` 를 쓰는 이유: `golden` 이 심링크다. `cp -r` 로 옮기면 깨질 수 있다.
(깨져도 `GOLDEN.txt` 폴백이 있어 골든은 복구되지만, tar 가 안전하다)

### 가져오기 (새 컴퓨터)

```bash
cd <새 작업폴더>
tar xzf comsol-hbm-ws.tar.gz

# 원본 mph 경로가 달라졌으므로 재지정한다 (파라메트릭 재검사도 함께 수행)
$CHBM_VENV/bin/python "$PLUGIN/app/init_ws.py" --source-mph "<새 경로>/원본.mph"
$CHBM_VENV/bin/python "$PLUGIN/app/init_ws.py" --status
```

`--status` 가 캘리브레이션 계수, 골든, 세대 수를 보여준다. 원본 경로가 깨져 있으면 경고한다.
COMSOL 경로는 자동 탐지되며(리눅스 `/opt`, `/usr/local`, macOS `/Applications`, 홈디렉터리),
못 찾으면 `COMSOL_ROOT` 또는 `project.json` 의 `comsol_cmd` 로 지정한다.

### 절대경로 감사

코드에는 사용자/장치 고유 경로가 없다. 이식 후 확인하려면:

```bash
git ls-files -z | xargs -0 grep -nHE '/home/|/media/|/Users/|/tmp/'
```

결과가 비어야 정상이다. (COMSOL 표준 설치 경로 glob 은 `workspace.py` 안에 있고
절대경로 하드코딩이 아니라 탐지 패턴이다)

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
