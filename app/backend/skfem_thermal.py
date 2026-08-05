# gmsh 메시 위에서 정상상태 이방성 열전도를 푸는 오픈소스 백엔드 (COMSOL 대체 검증용)
"""
푸는 방정식 (원본 COMSOL ht 인터페이스와 동일):

    -div(k grad T) = 0            (열원 없음 - 원본 모델에 HeatSource 노드가 없다)
    T = T_hot                     on "hot"   (temp1: 고정 358.15 K)
    -k dT/dn = h (T - T_ext)      on "conv"  (hf1: 대류, h=15000, T_ext=293.15)
    -k dT/dn = 0                  그 외      (ins1: 단열)

k 는 층별 이방성 대각텐서 diag(k_xy, k_xy, k_z).
"""

import sys
from pathlib import Path

import numpy as np
from skfem import (Basis, BilinearForm, ElementTetP1, FacetBasis, LinearForm,
                   MeshTet, condense, solve)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from params import Params  # noqa: E402


@BilinearForm
def _conduction(u, v, w):
    return (w["kx"] * u.grad[0] * v.grad[0]
            + w["ky"] * u.grad[1] * v.grad[1]
            + w["kz"] * u.grad[2] * v.grad[2])


@BilinearForm
def _robin(u, v, w):
    return w["h"] * u * v


@LinearForm
def _robin_rhs(v, w):
    return w["h"] * w["Text"] * v


def _elementwise(mesh, vol_props, nqp):
    """서브도메인별 k 를 요소 배열로 펼친다."""
    ne = mesh.t.shape[1]
    kx = np.full(ne, np.nan)
    kz = np.full(ne, np.nan)
    # meshio 가 'gmsh:bounding_entities' 같은 보조 키를 섞어 넣으므로
    # 물성 테이블 쪽을 기준으로 순회한다. 누락은 아래 NaN 검사가 잡는다.
    for name, (a, b) in vol_props.items():
        idx = mesh.subdomains.get(name)
        if idx is None:
            raise KeyError(f"메시에 서브도메인 '{name}' 이 없다")
        kx[idx] = a
        kz[idx] = b
    missing = int(np.isnan(kx).sum())
    if missing:
        raise RuntimeError(f"물성이 배정되지 않은 요소 {missing}개 - 물리그룹 누락")
    tile = lambda a: np.tile(a[:, None], (1, nqp))
    return tile(kx), tile(kx), tile(kz)


def solve_case(mesh_path: str, vol_props: dict, pm: Params):
    """메시를 읽어 정상상태 온도장을 푼다.

    반환 dict:
      T_max   전체 최대 온도 [K]
      T_max_stack / T_max_hs   다이스택 / 히트싱크 최대 온도 [K]
      Q_conv  대류면으로 빠져나간 총 열유량 [W]
      R_th    (T_hot - T_ext) / Q_conv  [K/W]
      A_conv  대류 유효 표면적 [m^2]
    """
    mesh = MeshTet.load(mesh_path)
    if "hot" not in mesh.boundaries or "conv" not in mesh.boundaries:
        raise RuntimeError(f"경계 물리그룹 누락: {list(mesh.boundaries)}")

    e = ElementTetP1()
    basis = Basis(mesh, e)
    nqp = basis.X.shape[1]
    kx, ky, kz = _elementwise(mesh, vol_props, nqp)

    A = _conduction.assemble(basis, kx=kx, ky=ky, kz=kz)

    fb = FacetBasis(mesh, e, facets=mesh.boundaries["conv"])
    ones = np.ones((fb.X.shape[1],))
    hq = np.tile(pm.h_conv * ones, (fb.nelems, 1))
    Tq = np.tile(pm.T_ext * ones, (fb.nelems, 1))
    A += _robin.assemble(fb, h=hq)
    b = _robin_rhs.assemble(fb, h=hq, Text=Tq)

    D = basis.get_dofs(mesh.boundaries["hot"])
    T = basis.zeros()
    T[D] = pm.T_hot
    T = solve(*condense(A, b, x=T, D=D))

    # 대류면 열유량 Q = integral h (T - T_ext) dS
    Tf = fb.interpolate(T)

    @LinearForm
    def _one(v, w):
        return 1.0 * v

    area = _one.assemble(fb).sum()
    q_int = fb.integrate(pm.h_conv * (Tf - pm.T_ext)) if hasattr(fb, "integrate") else None
    if q_int is None:
        # skfem 버전에 integrate 가 없으면 직접 구적
        q_int = float(np.sum(fb.dx * (pm.h_conv * (Tf.value - pm.T_ext))))
    Q = float(q_int)

    def submax(prefix):
        dofs = set()
        for name, idx in mesh.subdomains.items():
            if name.startswith(prefix):
                dofs.update(np.unique(mesh.t[:, idx]).tolist())
        return float(T[sorted(dofs)].max()) if dofs else float("nan")

    stack_max = max(submax("logic_die"), submax("dram"))
    hs_max = max(submax("hs_base"), submax("pin_"))

    # 면적 지표: HBM 은 인터포저 면적이 비싼 자원이라 Z 높이만큼 중요하다.
    foot = pm.dram_die_size ** 2
    span = (pm.n - 1) * pm.p + 2 * pm.r_pin      # 핀 배열이 실제로 차지하는 한 변
    return {
        "T": T,
        "footprint": foot,
        "area_ratio": float(area / foot),        # 대류면적 / 풋프린트 (증배율)
        "array_span": span,
        "footprint_use": float(span / pm.dram_die_size),
        "n_pins": pm.n ** 2,
        "T_max": float(T.max()),
        "T_min": float(T.min()),
        "T_max_stack": stack_max,
        "T_max_hs": hs_max,
        "Q_conv": Q,
        "R_th": (pm.T_hot - pm.T_ext) / Q if Q > 0 else float("inf"),
        "A_conv": float(area),
        "n_dofs": int(basis.N),
    }
