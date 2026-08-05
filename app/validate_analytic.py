# 해석해 대조군 - 원통핀 1개를 격리해 FEM 솔버(전도+Robin)를 이론식과 직접 대조한다
"""
검증 대상은 전체 모델이 아니라 '솔버 구현'이다. 원통 핀 1개, 밑면 고정온도,
측면+끝면 대류라는 교과서 문제를 그대로 풀어 이론식과 비교한다.

끝단 대류를 포함한 균일단면 핀의 엄밀해 (Incropera, Table 3.4 case A):

    q_f = M * (sinh(mL) + (h/(m k)) cosh(mL)) / (cosh(mL) + (h/(m k)) sinh(mL))
    m   = sqrt(h P / (k A_c)),   M = sqrt(h P k A_c) * (T_b - T_inf)
    P   = 2 pi r,  A_c = pi r^2

이 1차원 해는 반경방향 온도가 균일하다고 가정한다. Biot 수 h r / k 가 작아야
유효하며, 본 조건에서는 15000*75e-6/400 = 2.8e-3 로 충분히 작다.
"""

import sys
from pathlib import Path

import gmsh
import numpy as np
from skfem import (Basis, BilinearForm, ElementTetP1, FacetBasis, LinearForm,
                   MeshTet, condense, solve)

sys.path.insert(0, str(Path(__file__).resolve().parent))

R = 75e-6
L = 300e-6
K = 400.0          # Cu
H = 15000.0
T_B = 358.15
T_INF = 293.15


def analytic():
    P = 2 * np.pi * R
    Ac = np.pi * R ** 2
    m = np.sqrt(H * P / (K * Ac))
    M = np.sqrt(H * P * K * Ac) * (T_B - T_INF)
    mL = m * L
    hmk = H / (m * K)
    q = M * (np.sinh(mL) + hmk * np.cosh(mL)) / (np.cosh(mL) + hmk * np.sinh(mL))
    eta = q / (H * (P * L + Ac) * (T_B - T_INF))
    return dict(m=m, mL=mL, Bi=H * R / K, q=q, eta=eta,
                A=P * L + Ac)


def fem(mesh_size):
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("fin")
        occ = gmsh.model.occ
        cyl = occ.addCylinder(0, 0, 0, 0, 0, L, R)
        occ.synchronize()
        pg = gmsh.model.addPhysicalGroup(3, [cyl])
        gmsh.model.setPhysicalName(3, pg, "fin")

        base, conv = [], []
        for (dim, tag) in gmsh.model.getEntities(2):
            com = occ.getCenterOfMass(dim, tag)
            (base if com[2] < 1e-10 else conv).append(tag)
        pg = gmsh.model.addPhysicalGroup(2, base)
        gmsh.model.setPhysicalName(2, pg, "hot")
        pg = gmsh.model.addPhysicalGroup(2, conv)
        gmsh.model.setPhysicalName(2, pg, "conv")

        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size / 4)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
        gmsh.model.mesh.generate(3)
        Path("runs/_analytic").mkdir(parents=True, exist_ok=True)
        gmsh.write("runs/_analytic/fin.msh")
    finally:
        gmsh.finalize()

    mesh = MeshTet.load("runs/_analytic/fin.msh")
    e = ElementTetP1()
    basis = Basis(mesh, e)

    @BilinearForm
    def cond(u, v, w):
        return K * sum(u.grad[i] * v.grad[i] for i in range(3))

    @BilinearForm
    def rob(u, v, w):
        return H * u * v

    @LinearForm
    def rhs(v, w):
        return H * T_INF * v

    fb = FacetBasis(mesh, e, facets=mesh.boundaries["conv"])
    A = cond.assemble(basis) + rob.assemble(fb)
    b = rhs.assemble(fb)
    D = basis.get_dofs(mesh.boundaries["hot"])
    T = basis.zeros()
    T[D] = T_B
    T = solve(*condense(A, b, x=T, D=D))

    Tf = fb.interpolate(T)
    q = float(np.sum(fb.dx * (H * (Tf.value - T_INF))))
    area = float(np.sum(fb.dx))
    return q, area, basis.N, float(T.min())


def main():
    a = analytic()
    print("해석해 (Incropera Table 3.4 case A, 끝단 대류 포함)")
    print(f"  Biot = h r / k      = {a['Bi']:.3e}   (1D 가정 유효 조건: << 1)")
    print(f"  m                   = {a['m']:.1f} 1/m")
    print(f"  mL                  = {a['mL']:.4f}")
    print(f"  대류 표면적          = {a['A']:.4e} m^2")
    print(f"  q_fin               = {a['q']:.6f} W")
    print(f"  핀 효율             = {a['eta']*100:.2f} %")
    print()
    print(f"{'hmax[um]':>9} {'dofs':>8} {'area[m^2]':>12} {'q_FEM[W]':>11} "
          f"{'오차%':>9} {'T_tip[K]':>10}")
    last = None
    for s in [40e-6, 25e-6, 16e-6, 10e-6]:
        q, area, n, tmin = fem(s)
        err = 100 * (q - a["q"]) / a["q"]
        print(f"{s*1e6:9.0f} {n:8d} {area:12.4e} {q:11.6f} {err:+9.3f} {tmin:10.3f}")
        last = err
    print()
    ok = abs(last) < 5.0
    print(f"판정: 최종 오차 {last:+.3f}% -> {'PASS (5% 이내)' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
