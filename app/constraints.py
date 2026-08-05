# 공정 제약 필터 - 물리적으로 유리하지만 만들 수 없는 후보를 걸러낸다
"""
최적화기는 물리만 본다. 그래서 "다이 사이 15um NCF 자리에 In 솔더를 넣어라" 같은,
열적으로는 맞지만 공정상 불가능한 답을 최적이라고 보고한다.

이 모듈은 그런 후보를 걸러내는 규칙 집합이다. Vivado 스윕에서 impl 전략을
고르듯, 규칙을 통째로 끄거나(process_constraints=False) 개별로 끌 수 있다.

규칙을 끄는 것 자체는 잘못이 아니다 - 탐색 초기에 물리적 상한을 보고 싶을 때는
꺼두는 것이 맞다. 다만 그렇게 얻은 답은 '제작 가능성 미검증'으로 표시된다.

각 규칙: fn(pm) -> None(통과) 또는 사유 문자열(탈락)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from params import MATERIAL_CLASS  # noqa: E402

um = 1e-6

# 경계 비교 허용오차 [m]. 최적해가 제약선 위를 미끄러지므로 관심 지점이 전부
# 경계에 정확히 놓인다. 허용오차가 없으면 부동소수점 잔차(1e-20 수준)가
# 어느 후보를 살릴지 결정해 버린다. 1 pm 은 물리적으로 무의미하고 float 잡음보다 크다.
TOL = 1e-12


def _below(value, limit):
    """value 가 limit 미만인가 (경계값은 통과로 본다)."""
    return value < limit - TOL


def _above(value, limit):
    """value 가 limit 초과인가 (경계값은 통과로 본다)."""
    return value > limit + TOL

# 규칙 파라미터 (공정 능력에 맞춰 조정하는 값)
MAX_PIN_ASPECT = 5.0       # h_pin / (2*r_pin) 상한 - 전주/에칭 한계
MIN_PIN_DIAMETER = 50 * um  # 2*r_pin 하한
MIN_FLOW_GAP = 50 * um      # 핀 사이 유로 폭 하한 (p - 2*r_pin)
MIN_BASE_THICKNESS = 30 * um  # 히트싱크 베이스 최소 두께 (취급/평탄도)
NO_MICROPIN_MATERIALS = {"Graphite", "CVD_Dia"}

# 패키지 Z 높이 예산 [m]. 다이스택 상단(z_hs) + 베이스 + 핀 의 총합 상한.
# 시스템 스펙이며 발주처/모듈 설계에서 받아야 하는 값이다. 아래는 잠정값.
MAX_PACKAGE_HEIGHT = 1500 * um


def set_limits(**kw):
    """제약 파라미터를 덮어쓴다 (goal.json 의 limits 절에서 호출)."""
    g = globals()
    unknown = [k for k in kw if k not in g]
    if unknown:
        raise KeyError(f"알 수 없는 제약 파라미터: {unknown}")
    g.update(kw)


def die_attach_dielectric(pm):
    """다이 간 접합층은 절연성 본딩 필름이어야 한다.

    이 층에는 직경 25um Cu 범프가 70um 피치로 박혀 있다. 금속 접합재를 쓰면
    인접 범프가 단락된다. NCF 가 쓰이는 이유가 열이 아니라 전기/기계 요구조건이다.
    """
    cls = MATERIAL_CLASS.get(pm.tim_material)
    if cls != "polymer":
        return (f"다이 접합층 {pm.tim_material}({cls}) 은 절연 본딩 필름이 아니다 - "
                f"Cu 범프 간 단락. 폴리머 계열만 가능")
    return None


def pin_aspect_ratio(pm):
    """핀 종횡비 상한. 전주도금/딥에칭 공정 한계."""
    ar = pm.h_pin / (2 * pm.r_pin)
    if _above(ar, MAX_PIN_ASPECT):
        return (f"핀 종횡비 {ar:.2f} > {MAX_PIN_ASPECT} "
                f"(h_pin={pm.h_pin*1e6:.0f}um / 직경={2*pm.r_pin*1e6:.0f}um)")
    return None


def min_feature_size(pm):
    """최소 가공 치수."""
    d = 2 * pm.r_pin
    if _below(d, MIN_PIN_DIAMETER):
        return f"핀 직경 {d*1e6:.0f}um < 최소 가공치수 {MIN_PIN_DIAMETER*1e6:.0f}um"
    return None


def flow_gap(pm):
    """핀 사이에 냉각재가 지날 유로가 남아야 한다.

    이 규칙이 없으면 최적화기는 핀 직경을 피치까지 키워 유로를 완전히 막는다.
    (열적으로는 표면적이 최대가 되므로 '최적'으로 보인다)
    """
    gap = pm.p - 2 * pm.r_pin
    if _below(gap, MIN_FLOW_GAP):
        return (f"핀 간 유로 {gap*1e6:.0f}um < {MIN_FLOW_GAP*1e6:.0f}um "
                f"(p={pm.p*1e6:.0f}um, 직경={2*pm.r_pin*1e6:.0f}um)")
    return None


def micropin_manufacturable(pm):
    """미세 핀 배열로 가공 불가능한 재료."""
    if pm.hs_material in NO_MICROPIN_MATERIALS:
        return (f"{pm.hs_material} 은 이 치수의 미세 핀 배열로 가공할 수 없다 "
                f"(취성/이방성 재료)")
    return None


def anisotropy_orientation(pm):
    """이방성 재료를 고전도축이 핀 축과 맞도록 배향하는 것은 별도 공정이 필요하다."""
    from params import MATERIALS
    k = MATERIALS[pm.hs_material][2]
    if isinstance(k, tuple) and pm.anisotropic and pm.hs_orientation == "z":
        return (f"{pm.hs_material} 의 고전도축을 핀 축(z)에 정렬하려면 배향 공정이 "
                f"필요하다 - 시트 재료의 자연 배향은 면내(xy)")
    return None


def package_height(pm):
    """패키지 Z 높이 예산.

    핀을 높일수록 열은 잘 빠진다 - 이 모델 안에서는 상한이 없다. 실제 상한은
    열이 아니라 패키지 두께 스펙이다. 이 규칙이 없으면 최적화는 '핀을 무한히
    높게'로 수렴한다.
    """
    total = pm.z_hs + pm.t_base + pm.h_pin
    if _above(total, MAX_PACKAGE_HEIGHT):
        return (f"패키지 높이 {total*1e6:.0f}um > 예산 {MAX_PACKAGE_HEIGHT*1e6:.0f}um "
                f"(스택 {pm.z_hs*1e6:.0f} + 베이스 {pm.t_base*1e6:.0f} + 핀 {pm.h_pin*1e6:.0f})")
    return None


def min_base_thickness(pm):
    """베이스 최소 두께. 얇을수록 열저항은 낮지만 취급/평탄도 한계가 있다."""
    if _below(pm.t_base, MIN_BASE_THICKNESS):
        return f"베이스 두께 {pm.t_base*1e6:.0f}um < 최소 {MIN_BASE_THICKNESS*1e6:.0f}um"
    return None


RULES = {
    "package_height": package_height,
    "min_base_thickness": min_base_thickness,
    "die_attach_dielectric": die_attach_dielectric,
    "pin_aspect_ratio": pin_aspect_ratio,
    "min_feature_size": min_feature_size,
    "flow_gap": flow_gap,
    "micropin_manufacturable": micropin_manufacturable,
    "anisotropy_orientation": anisotropy_orientation,
}


def check(pm, enabled=True, disabled_rules=()):
    """공정 제약 검사. 반환 (violations, applied_rules).

    enabled=False 면 검사하지 않고 빈 리스트를 돌려준다.
    """
    if not enabled:
        return [], []
    applied, bad = [], []
    for name, fn in RULES.items():
        if name in disabled_rules:
            continue
        applied.append(name)
        reason = fn(pm)
        if reason:
            bad.append({"rule": name, "reason": reason})
    return bad, applied


def describe():
    lines = ["공정 제약 규칙:"]
    for name, fn in RULES.items():
        doc = (fn.__doc__ or "").strip().splitlines()[0]
        lines.append(f"  {name:26s} {doc}")
    lines += [
        "",
        f"  MAX_PIN_ASPECT     = {MAX_PIN_ASPECT}",
        f"  MIN_PIN_DIAMETER   = {MIN_PIN_DIAMETER*1e6:.0f} um",
        f"  MIN_FLOW_GAP       = {MIN_FLOW_GAP*1e6:.0f} um",
        f"  NO_MICROPIN        = {', '.join(sorted(NO_MICROPIN_MATERIALS))}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
