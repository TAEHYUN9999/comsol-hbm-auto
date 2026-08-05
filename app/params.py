# HBM 핀히트싱크 모델의 전역 매개변수 (원본 .mph dmodel.xml 에서 추출)
"""
출처: HBM_finheatsink_직경150 -높이300_1.0.mph / <ModelParam tag="param">
단위는 전부 SI (m, W, K). 원본은 [um]/[mm] 표기였으나 여기서는 m 로 환산해 둔다.
"""

from dataclasses import dataclass, replace

um = 1e-6
mm = 1e-3

# 기하 경계 비교 허용오차 [m]. constraints.TOL 과 같은 이유 - 최적해가
# 제약선 위에 놓이므로 부동소수점 잔차가 판정을 바꾸면 안 된다.
_TOL = 1e-12


@dataclass(frozen=True)
class Params:
    # --- 다이 스택 ---
    t_die: float = 32 * um            # DRAM/로직 다이 두께
    t_ncf: float = 15 * um            # NCF 접합층 두께
    t_top: float = 156 * um           # 최상단 다이 두께 (원본 정의, 현 스택 계산엔 미사용)
    dram_die_size: float = 1.2 * mm
    logic_die_size: float = 1.2 * mm
    n_dram: int = 12                  # 유도값: z_hs = t_die + n_dram*(t_ncf+t_die) 로 역산

    # --- 인터커넥트 ---
    bump_r: float = 12.5 * um
    tsv_r: float = 10.0 * um
    pitch: float = 70 * um            # 범프/TSV 피치

    # --- 히트싱크 (설계 변수) ---
    t_base: float = 0.10 * mm
    r_pin: float = 75 * um            # 폴더명 "직경150" = 2*r_pin
    h_pin: float = 300 * um           # 폴더명 "높이300"
    p: float = 301 * um               # 핀 피치
    n: int = 4                        # 핀 배열 n x n

    # --- 재료 (설계 변수) ---
    hs_material: str = "Cu"           # 히트싱크 베이스+핀 재질
    tim_material: str = "NCF"         # 다이 접합층 재질

    # --- 캘리브레이션 (COMSOL 기준값으로 역산해 채운다. 설계 변수 아님) ---
    stack_k_factor: float = 1.0       # 다이스택 유효 k_z 보정계수

    # --- 모델 가정 스위치 (설계 변수 아님. Vivado impl 전략 고르듯 켜고 끈다) ---
    anisotropic: bool = True          # 이방성 재료를 이방성으로 풀 것인가
    hs_orientation: str = "z"         # 이방성 히트싱크의 고전도축 ("z" | "xy")
    process_constraints: bool = True  # 공정 제약 필터 적용 여부
    disabled_rules: tuple = ()        # 개별로 끌 규칙 이름들

    # --- 경계조건 ---
    T_hot: float = 358.15             # temp1: 고정 온도 경계 [K] (85 degC)
    h_conv: float = 15000.0           # hf1: 대류계수 [W/(m^2 K)] (UserDef, h_model="fixed" 일 때만)
    T_ext: float = 293.15             # hf1: 외부 온도 [K] (20 degC)

    # --- 냉각 모델 (스위치) ---
    h_model: str = "fixed"            # "fixed" | "velocity" | "pumping_power"
    coolant: str = "water"
    v_inf: float = 0.05               # h_model="velocity" 일 때 접근 유속 [m/s]
    p_pump: float = 1.0e-3            # h_model="pumping_power" 일 때 펌핑파워 [W]

    # --- 메시 ---
    hmax: float = 180 * um            # 원본 MeshSizeDefault hmax
    hmin: float = 33.6 * um           # 원본 MeshSizeDefault hmin

    # ------------------------------------------------------------------
    @property
    def z_hs(self) -> float:
        """히트싱크 베이스 하단 z. 원본 파라미터 z_hs = 596e-6 과 일치해야 한다."""
        return self.t_die + self.n_dram * (self.t_ncf + self.t_die)

    @property
    def x0(self) -> float:
        """핀 배열 원점. 원본: (dram_die_size-(n-1)*p)/2"""
        return (self.dram_die_size - (self.n - 1) * self.p) / 2

    @property
    def y0(self) -> float:
        return (self.dram_die_size - (self.n - 1) * self.p) / 2

    def with_(self, **kw) -> "Params":
        return replace(self, **kw)

    def check(self) -> list[str]:
        """설계 제약. 위반 항목 리스트를 돌려준다 (빈 리스트 = 통과)."""
        bad = []
        if (self.n - 1) * self.p > self.dram_die_size + _TOL:
            bad.append(f"핀 배열이 다이를 벗어남: (n-1)*p={(self.n-1)*self.p:.3e} > {self.dram_die_size:.3e}")
        if 2 * self.r_pin >= self.p + _TOL:
            bad.append(f"핀 간섭: 2*r_pin={2*self.r_pin:.3e} >= p={self.p:.3e}")
        if self.x0 - self.r_pin < -_TOL:
            bad.append(f"핀이 다이 경계 밖으로 나감: x0-r_pin={self.x0-self.r_pin:.3e} < 0")
        if self.h_pin < 2 * self.hmin - _TOL:
            bad.append(f"핀 높이가 메시 하한 대비 부족: h_pin={self.h_pin:.3e} < 2*hmin={2*self.hmin:.3e}")
        if self.r_pin < self.hmin - _TOL:
            bad.append(f"핀 반경이 메시 하한 미만: r_pin={self.r_pin:.3e} < hmin={self.hmin:.3e}")
        for field, name in [("hs_material", self.hs_material), ("tim_material", self.tim_material)]:
            if name not in MATERIALS:
                bad.append(f"{field}: 미등록 재료 {name!r}")
        return bad


# 원본 .mph 와 동일한 조건 (직경 150um, 높이 300um)
BASELINE = Params()


# ----------------------------------------------------------------------
# 재료 물성 (원본 Material 노드에서 추출, 온도 의존성 없음)
# 이름:            (rho [kg/m^3], Cp [J/(kg K)], k [W/(m K)])
# k 는 등방이면 float, 이방성이면 (k_고전도축, k_저전도축) 튜플.
# 튜플 재료는 anisotropic 스위치를 끄면 k_고전도축 값으로 등방 취급된다 (낙관적 근사).
MATERIALS = {
    # --- 원본 .mph 에 정의된 4종 ---
    "Si":     (2330.0, 700.0, 130.0),
    "Cu":     (8960.0, 385.0, 400.0),
    "NCF":    (1200.0, 1100.0, 1.0),
    "SAC305": (7370.0, 230.0, 58.7),

    # --- 재료 탐색용 후보 (문헌 상온 대표값) ---
    # 히트싱크 후보
    "Al":       (2700.0, 900.0, 237.0),    # 가볍고 싸지만 k 낮음
    "Ag":       (10490.0, 235.0, 429.0),   # k 최고 금속, 고가
    "AlN":      (3260.0, 740.0, 180.0),    # 절연 세라믹
    "AlSiC":    (3000.0, 741.0, 200.0),    # CTE 정합 목적
    # 열분해 그래파이트(APG): 면내 1500, 두께방향 8. 200배 이방성.
    "Graphite": (2200.0, 710.0, (1500.0, 8.0)),
    "CVD_Dia":  (3510.0, 509.0, 2000.0),   # 다이아몬드는 입방정 - 실제로 등방
    # TIM / 접합층 후보
    "TIM_hi":   (2500.0, 800.0, 5.0),      # 고성능 열전도 접착제
    "Solder_In": (7310.0, 233.0, 82.0),    # In 솔더 TIM
}

# 공정 제약 판정에 쓰는 재료 분류
MATERIAL_CLASS = {
    "Si": "semiconductor", "Cu": "metal", "Ag": "metal", "Al": "metal",
    "SAC305": "metal", "Solder_In": "metal",
    "NCF": "polymer", "TIM_hi": "polymer",
    "AlN": "ceramic", "CVD_Dia": "ceramic", "AlSiC": "mmc", "Graphite": "carbon",
}

# 설계 변수로 허용하는 후보 (탐색기가 이 목록에서만 고른다)
HS_CANDIDATES = ["Cu", "Al", "Ag", "AlN", "AlSiC", "Graphite"]
TIM_CANDIDATES = ["NCF", "TIM_hi", "Solder_In"]


def material_k(name: str, anisotropic: bool = True, orientation: str = "z"):
    """재료의 열전도도를 (k_xy, k_z) 로 돌려준다.

    anisotropic=False 면 이방성 재료도 고전도축 값으로 등방 취급한다.
    이는 데이터시트 헤드라인 숫자만 보고 쓰는 것과 같으며 성능을 과대평가한다.
    스위치로 남겨둔 이유는 그 과대평가 폭을 직접 재기 위해서다.

    orientation: 이방성 재료의 고전도축을 어디로 두는가.
      "z"  - 핀 축 방향 (열이 빠져나가는 방향. 공학적으로 원하는 배향)
      "xy" - 면내 방향 (APG 시트의 자연 배향. 핀으로 세우면 이쪽이 된다)
    """
    k = MATERIALS[name][2]
    if not isinstance(k, tuple):
        return (k, k)
    k_hi, k_lo = k
    if not anisotropic:
        return (k_hi, k_hi)
    return (k_lo, k_hi) if orientation == "z" else (k_hi, k_lo)


def homogenized_k(k_matrix: float, k_incl: float, f: float) -> tuple[float, float]:
    """원통 포유물이 z 방향으로 관통하는 층의 유효 열전도도.

    TSV/범프를 개별 형상으로 풀면 지오메트리 객체가 수천 개가 되어 스윕 루프에
    쓸 수 없다. 대신 층 단위 이방성 유효물성으로 치환한다.

      k_z  : 병렬 혼합칙 (경로가 z 로 직결이므로 정확)
      k_xy : Maxwell-Eucken (원통 횡방향 유효매질)

    f = 포유물 면적분율. 반환 (k_xy, k_z).
    """
    k_z = f * k_incl + (1.0 - f) * k_matrix
    num = k_incl * (1.0 + f) + k_matrix * (1.0 - f)
    den = k_incl * (1.0 - f) + k_matrix * (1.0 + f)
    k_xy = k_matrix * num / den
    return k_xy, k_z
