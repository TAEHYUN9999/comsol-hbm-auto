# 대류계수 h 를 형상의 함수로 만드는 냉각 모델 - D-2(최적화 발산)의 근본 해결
"""
원본 모델은 h = 15000 W/(m^2 K) 를 형상과 무관한 상수로 박아 두었다.
그러면 표면적을 늘릴수록 무조건 이득이라 최적화가 탐색범위 모서리로 발산한다.

실제로는 핀을 키우거나 촘촘히 하면 유로가 좁아져 압력강하가 커지고,
같은 펌핑파워로는 유속이 떨어져 h 가 감소한다. 이 커플링이 있어야
내부 최적해가 생긴다.

h 모델 3가지 (Params.h_model 로 전환):

  "fixed"          h = h_conv 상수. 원본 모델과 동일. 발산함.
  "velocity"       유속을 고정하고 Zukauskas 상관식으로 h(형상, V).
                   여전히 큰 핀이 유리한 쪽으로 치우친다 (압력강하 무시).
  "pumping_power"  펌핑파워를 고정하고 유속을 역산. 진짜 트레이드오프.  <- 권장

상관식: Zukauskas 관군(tube bank) 대류/마찰. 정렬배열(inline) 기준.
  Nu = C * Re_max^m * Pr^0.36 * C2(N_L)
  Re_max = rho V_max D / mu,  V_max = V_inf * S_T/(S_T - D)

주의 - 적용범위: Zukauskas 는 Re_max >= 10 에서 정의되며, 마찰계수 상관식은
Re_max >= 1e3 구간의 것이다. 마이크로 핀휜은 그보다 낮은 Re 에서 동작하는
경우가 많다. 범위를 벗어나면 diag["warnings"] 에 기록한다.
절대값은 불확실할 수 있으나, 최적해의 위치를 만드는 것은 스케일링 추세이며
그 추세(면적 증가 vs 유속 감소)는 범위 밖에서도 방향이 유지된다.
"""

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 상온(300K) 물성: (rho [kg/m^3], mu [Pa s], k [W/(m K)], cp [J/(kg K)])
COOLANTS = {
    "water":  (997.0, 8.90e-4, 0.613, 4180.0),
    "FC72":   (1680.0, 6.40e-4, 0.057, 1100.0),   # 유전체 액침냉각용
    "air":    (1.18, 1.85e-5, 0.0262, 1005.0),
}


def props(name):
    rho, mu, k, cp = COOLANTS[name]
    return rho, mu, k, cp, mu * cp / k     # 마지막이 Pr


# Zukauskas 정렬배열 계수: (Re 하한, Re 상한, C, m)
_ZK = [
    (0.0, 1e2, 0.80, 0.40),
    (1e2, 1e3, 0.51, 0.50),      # 이 구간은 단일 원통에 준함
    (1e3, 2e5, 0.27, 0.63),
    (2e5, 2e6, 0.021, 0.84),
]

# 열 방향 관 열수 N_L 보정 (정렬배열)
_C2 = {1: 0.70, 2: 0.80, 3: 0.86, 4: 0.90, 5: 0.92, 7: 0.95, 10: 0.97, 13: 0.98, 16: 0.99}


def _c2(nl):
    keys = sorted(_C2)
    if nl >= keys[-1]:
        return 1.0
    for a, b in zip(keys, keys[1:]):
        if a <= nl <= b:
            t = (nl - a) / (b - a)
            return _C2[a] + t * (_C2[b] - _C2[a])
    return _C2[keys[0]]


def nusselt(re_max, pr, n_l):
    for lo, hi, C, m in _ZK:
        if lo <= re_max < hi:
            return C * re_max ** m * pr ** 0.36 * _c2(n_l)
    C, m = _ZK[-1][2], _ZK[-1][3]
    return C * re_max ** m * pr ** 0.36 * _c2(n_l)


def friction_factor(re_max, pt, pl):
    """정렬배열 마찰계수 (Zukauskas/Gunter-Shaw 계열 근사)."""
    if re_max <= 0:
        return 0.0
    f = (0.044 + 0.08 * pl / (pt - 1.0) ** (0.43 + 1.13 / pl)) * re_max ** -0.15
    # 저 Re 에서는 층류 지배라 마찰이 급증한다. 관내 층류(f ~ 64/Re) 형태로 하한을 준다.
    f_lam = 64.0 / max(re_max, 1e-6) / 4.0
    return max(f, f_lam) if re_max < 1e3 else f


def hydraulics(pm, v_inf):
    """유속 v_inf [m/s] 에서의 h, 압력강하, 펌핑파워를 계산한다."""
    rho, mu, k, cp, pr = props(pm.coolant)
    D = 2 * pm.r_pin
    S_T = pm.p                       # 유동 직교방향 피치
    S_L = pm.p                       # 유동방향 피치 (정사각 배열)
    gap = S_T - D
    warnings = []
    if gap <= 0:
        return None

    v_max = v_inf * S_T / gap
    re_max = rho * v_max * D / mu
    nu = nusselt(re_max, pr, pm.n)
    h = nu * k / D

    pt, pl = S_T / D, S_L / D
    f = friction_factor(re_max, pt, pl)
    dp = pm.n * f * rho * v_max ** 2 / 2.0        # N_L 열 통과

    # 정면 유동 단면 = 다이 한 변 x 핀 높이
    a_front = pm.dram_die_size * pm.h_pin
    q_vol = v_inf * a_front
    p_pump = dp * q_vol

    if re_max < 10:
        warnings.append(f"Re_max={re_max:.1f} < 10 - Zukauskas 적용범위 미만")
    if re_max < 1e3:
        warnings.append(f"Re_max={re_max:.1f} < 1e3 - 마찰계수 상관식 범위 밖 (층류 하한 적용)")

    return {"h": h, "v_inf": v_inf, "v_max": v_max, "Re_max": re_max, "Nu": nu,
            "f": f, "dP": dp, "Q_vol": q_vol, "P_pump": p_pump,
            "gap": gap, "warnings": warnings}


def velocity_for_pumping_power(pm, p_target, lo=1e-4, hi=50.0):
    """주어진 펌핑파워를 소비하는 유속을 역산한다. P ~ V^3 이라 단조."""
    def g(v):
        r = hydraulics(pm, v)
        return (r["P_pump"] - p_target) if r else 1e9
    if hydraulics(pm, lo) is None:
        return None
    try:
        return brentq(g, lo, hi, xtol=1e-9, rtol=1e-10)
    except ValueError:
        return None


def effective_h(pm):
    """Params 의 h_model 에 따라 실제로 쓸 h 를 정한다.

    반환 (h, diag). 유로가 막혔거나 해를 못 찾으면 (None, diag).
    """
    if pm.h_model == "fixed":
        return pm.h_conv, {"model": "fixed", "h": pm.h_conv,
                           "note": "형상과 무관한 상수 - 최적화가 발산한다"}

    if pm.h_model == "velocity":
        r = hydraulics(pm, pm.v_inf)
        if r is None:
            return None, {"model": "velocity", "error": "유로 폭 <= 0"}
        r["model"] = "velocity"
        return r["h"], r

    if pm.h_model == "pumping_power":
        v = velocity_for_pumping_power(pm, pm.p_pump)
        if v is None:
            return None, {"model": "pumping_power",
                          "error": "주어진 펌핑파워를 만족하는 유속 없음 (유로 막힘)"}
        r = hydraulics(pm, v)
        r["model"] = "pumping_power"
        r["P_pump_target"] = pm.p_pump
        return r["h"], r

    raise ValueError(f"알 수 없는 h_model: {pm.h_model!r}")


def calibrate_pumping_power(pm, h_target=15000.0):
    """기준 형상이 원본의 h=15000 을 내도록 펌핑파워를 역산한다.

    이렇게 앵커를 잡으면 스윕 결과가 '같은 펌핑 예산에서의 상대 성능'이 되어
    원본 모델과 비교 가능해진다.
    """
    def g(v):
        r = hydraulics(pm, v)
        return r["h"] - h_target if r else 1e9
    v = brentq(g, 1e-5, 100.0, xtol=1e-12, rtol=1e-12)
    return hydraulics(pm, v)


if __name__ == "__main__":
    from params import Params
    pm = Params()
    print(f"기준 형상: 직경 {2*pm.r_pin*1e6:.0f}um, 피치 {pm.p*1e6:.0f}um, "
          f"높이 {pm.h_pin*1e6:.0f}um, {pm.n}x{pm.n}")
    for c in COOLANTS:
        pmc = pm.with_(coolant=c)
        try:
            r = calibrate_pumping_power(pmc)
        except ValueError:
            print(f"  {c:6s} h=15000 을 낼 수 없음")
            continue
        print(f"  {c:6s} V={r['v_inf']*1000:8.3f} mm/s  Re_max={r['Re_max']:8.2f}  "
              f"dP={r['dP']:10.2f} Pa  P_pump={r['P_pump']*1e3:8.4f} mW"
              + ("  [" + "; ".join(r["warnings"]) + "]" if r["warnings"] else ""))
