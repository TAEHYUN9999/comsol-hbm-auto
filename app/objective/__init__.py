# 교체 가능한 목적함수 플러그인 - 발주처가 판정 기준을 확정하면 여기만 바꾼다
"""
루프 코드는 목적함수의 내용을 모른다. 등록된 이름만 보고 호출한다.

인터페이스:
    evaluate(result: dict, pm: Params) -> Score(value, minimize, detail)

주의: 어떤 기준으로 판정할지 미확정이므로 루프는 항상 전부를 계산해 로그에 남긴다.
나중에 기준이 바뀌어도 과거 실행을 재판정할 수 있게 하기 위함이다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    value: float
    minimize: bool
    detail: str


def tmax(result, pm):
    """전역 최고온도. 주의: 고정온도 경계가 최고점이면 설계에 반응하지 않는다."""
    return Score(result["T_max"], True, "전역 T_max [K]")


def tmax_stack(result, pm):
    """다이스택 내 최고온도. 원본 max1/max2 의 box 선택에 대응하는 후보."""
    return Score(result["T_max_stack"], True, "다이스택 T_max [K]")


def rth(result, pm):
    """열저항 (T_hot - T_ext)/Q. 히트싱크 설계 품질을 직접 재는 지표."""
    return Score(result["R_th"], True, "R_th [K/W]")


def q_conv(result, pm):
    """대류면 총 방열량. R_th 의 역수 관계지만 절대 성능으로 보기 편하다."""
    return Score(result["Q_conv"], False, "Q_conv [W]")


REGISTRY = {
    "tmax": tmax,
    "tmax_stack": tmax_stack,
    "rth": rth,
    "q_conv": q_conv,
}

DEFAULT = "rth"


def evaluate_all(result, pm):
    """등록된 목적함수를 전부 계산한다."""
    return {name: fn(result, pm) for name, fn in REGISTRY.items()}
