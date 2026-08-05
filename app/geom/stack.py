# HBM 다이스택 + 핀히트싱크의 파라메트릭 지오메트리/메시를 gmsh 로 생성한다
"""
원본 COMSOL 모델은 TSV/범프를 개별 형상으로 5,696개 만들어 둔다. 스윕 루프에서는
그 비용을 감당할 수 없으므로 층 단위 이방성 유효물성으로 치환한다 (params.homogenized_k).

층 해상도는 resolve_layers 로 고른다:
  "full"  - NCF/다이 층을 전부 개별 볼륨으로 (원본에 가깝고 비쌈, 검증용)
  "merged"- 반복 유닛 전체를 등가 이방성 블록 1개로 (스윕 루프용 기본값)

두 모드의 T_max 차이가 메시 수렴 오차 안에 들어오면 merged 를 신뢰할 수 있다.
"""

import sys
from pathlib import Path

import gmsh
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from params import Params, MATERIALS, homogenized_k, material_k  # noqa: E402


def layer_properties(pm: Params):
    """다이 층 / NCF 층의 유효 이방성 열전도도를 계산한다."""
    k_si = MATERIALS["Si"][2]
    k_cu = MATERIALS["Cu"][2]                  # TSV/범프는 Cu 고정 (공정 제약)
    # 접합층은 설계 변수. 층 내부는 등방으로 다루고, 층 방향 이방성은
    # 범프 유효물성(homogenized_k)이 만들어낸다.
    k_ncf = material_k(pm.tim_material, pm.anisotropic, "xy")[0]

    cell = pm.pitch ** 2
    f_tsv = np.pi * pm.tsv_r ** 2 / cell      # 다이 층의 TSV 면적분율
    f_bump = np.pi * pm.bump_r ** 2 / cell    # NCF 층의 범프 면적분율

    die_xy, die_z = homogenized_k(k_si, k_cu, f_tsv)
    ncf_xy, ncf_z = homogenized_k(k_ncf, k_cu, f_bump)
    return {
        "die": (die_xy, die_z, f_tsv),
        "ncf": (ncf_xy, ncf_z, f_bump),
    }


def build_layers(pm: Params, resolve_layers: str = "merged"):
    """z 하단부터 쌓이는 층 리스트를 만든다.

    반환: [(이름, 두께, k_xy, k_z), ...]  (히트싱크 제외, 다이스택만)
    """
    props = layer_properties(pm)
    die_xy, die_z, _ = props["die"]
    ncf_xy, ncf_z, _ = props["ncf"]

    layers = [("logic_die", pm.t_die, die_xy, die_z * pm.stack_k_factor)]

    if resolve_layers == "full":
        for i in range(pm.n_dram):
            layers.append((f"ncf{i}", pm.t_ncf, ncf_xy, ncf_z))
            layers.append((f"dram{i}", pm.t_die, die_xy, die_z))
    elif resolve_layers == "merged":
        # 반복 유닛 (NCF + 다이) x n_dram 을 등가 이방성 블록 1개로.
        # 층 직교 방향은 직렬(조화평균), 층 평행 방향은 병렬(산술평균) — 층상매질의 엄밀해.
        t_unit = pm.t_ncf + pm.t_die
        k_z_unit = t_unit / (pm.t_ncf / ncf_z + pm.t_die / die_z)
        k_xy_unit = (pm.t_ncf * ncf_xy + pm.t_die * die_xy) / t_unit
        # 유효물성은 범프/TSV 계면의 수축(constriction) 저항을 무시하므로 스택을
        # 실제보다 잘 통하게 만든다. 그 몫을 COMSOL 기준값으로 역산한 계수로 보정한다.
        k_z_unit *= pm.stack_k_factor
        layers.append(("dram_stack", pm.n_dram * t_unit, k_xy_unit, k_z_unit))
    else:
        raise ValueError(f"resolve_layers must be 'full' or 'merged', got {resolve_layers!r}")

    return layers


def generate(pm: Params, out_path: str, resolve_layers: str = "merged",
             mesh_size: float | None = None, verbose: bool = False):
    """지오메트리를 만들고 메시해 .msh 로 저장한다.

    반환: dict(layers=..., z_top=..., n_nodes=..., n_tets=...)
    물리그룹:
      볼륨  - 층 이름별 (재료 물성 부여용)
      면    - "hot"   : z=0 고정온도 경계 (temp1)
              "conv"  : 히트싱크 노출면 대류 경계 (hf1)
              나머지는 물리그룹 없음 -> 단열 (ins1)
    """
    bad = pm.check()
    if bad:
        raise ValueError("설계 제약 위반: " + "; ".join(bad))

    layers = build_layers(pm, resolve_layers)
    L = pm.dram_die_size
    if mesh_size is None:
        mesh_size = pm.hmax

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 1 if verbose else 0)
        gmsh.model.add("hbm")
        occ = gmsh.model.occ

        # --- 다이 스택 ---
        vols = []          # (tag, 이름, k_xy, k_z)
        z = 0.0
        for name, t, kxy, kz in layers:
            v = occ.addBox(0, 0, z, L, L, t)
            vols.append((v, name, kxy, kz))
            z += t
        z_stack_top = z

        # --- 히트싱크 베이스 ---
        # 이방성 재료(APG 등)는 배향에 따라 (k_xy, k_z) 가 뒤바뀐다.
        hs_xy, hs_z = material_k(pm.hs_material, pm.anisotropic, pm.hs_orientation)
        v = occ.addBox(0, 0, z, L, L, pm.t_base)
        vols.append((v, "hs_base", hs_xy, hs_z))
        z_base_top = z + pm.t_base

        # --- 핀 배열 ---
        pin_tags = []
        for i in range(pm.n):
            for j in range(pm.n):
                cx = pm.x0 + i * pm.p
                cy = pm.y0 + j * pm.p
                t = occ.addCylinder(cx, cy, z_base_top, 0, 0, pm.h_pin, pm.r_pin)
                pin_tags.append(t)
                vols.append((t, f"pin_{i}_{j}", hs_xy, hs_z))
        z_top = z_base_top + pm.h_pin

        # 공유 인터페이스를 만들기 위해 전체를 fragment
        all_dt = [(3, v[0]) for v in vols]
        frag, frag_map = occ.fragment(all_dt, [])
        occ.synchronize()

        # fragment 후 원래 볼륨 -> 새 볼륨 매핑
        name_of = {}
        for (orig, entry) in zip(vols, frag_map):
            for (dim, tag) in entry:
                if dim == 3:
                    name_of[tag] = orig[1:]  # (이름, k_xy, k_z)

        # --- 볼륨 물리그룹 ---
        by_name = {}
        for tag, (name, kxy, kz) in name_of.items():
            by_name.setdefault(name, []).append(tag)
        vol_props = {}
        for name, tags in by_name.items():
            pg = gmsh.model.addPhysicalGroup(3, tags)
            gmsh.model.setPhysicalName(3, pg, name)
            _, kxy, kz = (name,) + name_of[tags[0]][1:]
            vol_props[name] = (kxy, kz)

        # --- 경계면 분류 ---
        # 바운딩박스는 gmsh 가 tolerance 만큼 패딩하므로 평면 판정에 쓸 수 없다.
        # 무게중심 z 로 위치를 잡고, 인접 볼륨이 2개인 면(내부 접합면)은 제외한다.
        eps = 1e-10
        hot, conv = [], []
        for (dim, tag) in gmsh.model.getEntities(2):
            up, _ = gmsh.model.getAdjacencies(dim, tag)
            if len(up) != 1:
                continue                              # 내부 인터페이스 -> 경계 아님
            com = gmsh.model.occ.getCenterOfMass(dim, tag)
            if com[2] < eps:
                hot.append(tag)                       # z=0 : 고정온도 (temp1)
            elif com[2] > z_base_top - eps:
                conv.append(tag)                      # 베이스 상면 + 핀 측면/상면 : 대류 (hf1)
            # 그 외(스택 측면, 베이스 측면)는 단열 (ins1)

        if not hot:
            raise RuntimeError("z=0 고정온도 면을 찾지 못했다")
        if not conv:
            raise RuntimeError("대류 경계면을 찾지 못했다")

        pg = gmsh.model.addPhysicalGroup(2, hot)
        gmsh.model.setPhysicalName(2, pg, "hot")
        pg = gmsh.model.addPhysicalGroup(2, conv)
        gmsh.model.setPhysicalName(2, pg, "conv")

        # --- 메시 크기 ---
        # 얇은 층(NCF 15um)이 전역 크기를 지배하지 않도록 하한을 두되,
        # 핀은 반경의 1/2 이하로 잘라 곡률을 잡는다.
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(pm.hmin, pm.r_pin / 2))
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10)   # HXT (병렬 Delaunay)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        gmsh.write(out_path)

        nodes = gmsh.model.mesh.getNodes()[0].size
        etypes, etags, _ = gmsh.model.mesh.getElements(3)
        ntet = sum(len(t) for t in etags)

        return {
            "layers": layers,
            "vol_props": vol_props,
            "z_stack_top": z_stack_top,
            "z_base_top": z_base_top,
            "z_top": z_top,
            "n_nodes": int(nodes),
            "n_tets": int(ntet),
            "mesh_size": mesh_size,
            "resolve_layers": resolve_layers,
        }
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    pm = Params()
    print(f"z_hs 검산: 계산 {pm.z_hs*1e6:.1f} um vs 원본 596.0 um")
    props = layer_properties(pm)
    for k, (kxy, kz, f) in props.items():
        print(f"  {k:4s} f={f:.4f}  k_xy={kxy:8.2f}  k_z={kz:8.2f} W/(m K)")
    info = generate(pm, "runs/_probe/mesh.msh", verbose=True)
    print(info["n_nodes"], "nodes,", info["n_tets"], "tets")
