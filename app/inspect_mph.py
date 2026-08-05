# .mph 를 COMSOL 없이 해부한다 - 매개변수/지오메트리/재료/경계조건/스터디를 뽑는다
"""
.mph 는 ZIP 이고 모델 트리는 dmodel.xml 에 들어 있다. COMSOL 을 열지 않고도
자동화에 필요한 정보를 전부 읽을 수 있다.

가장 중요한 판정: **지오메트리가 파라메트릭인가.**
  CAD 임포트 형상이면 매개변수를 바꿔도 형상이 따라오지 않는다.
  이 경우 자동화 자체가 성립하지 않으므로 먼저 걸러내야 한다.

사용:
  python inspect_mph.py <파일.mph>
  python inspect_mph.py <파일.mph> --json      기계 판독용
"""

import argparse
import html
import json
import re
import sys
import zipfile

TXT = re.compile(r"\s+")


def _clean(s):
    return TXT.sub(" ", html.unescape(s)).strip()


def read_dmodel(path):
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist()]
        return z.read("dmodel.xml").decode("utf-8", "replace"), names


def parameters(d):
    out = {}
    for m in re.finditer(r'<expressions T="31" name="([^"]+)" expr="([^"]*)"', d):
        out[m.group(1)] = html.unescape(m.group(2))
    return out


def geom_features(d):
    out = []
    for m in re.finditer(r"<GeomFeature\b[^>]*>", d):
        t = m.group(0)
        op = re.search(r'op="([^"]+)"', t)
        tag = re.search(r'tag="([^"]+)"', t)
        nm = re.search(r'name="([^"]*)"', t)
        start = m.start()
        nxt = d.find("<GeomFeature", start + 10)
        blk = d[start: nxt if nxt > 0 else start + 6000]
        props = {}
        for p in re.finditer(r'<propertyValue T="\d+"([^>]*?)name="p:([^"]+)"', blk):
            v = re.search(r'value="([^"]*)"', p.group(1)) or \
                re.search(r'valueMatrix="([^"]*)"', p.group(1))
            if v:
                props[p.group(2)] = html.unescape(v.group(1))
        out.append({
            "op": op.group(1) if op else "?",
            "tag": tag.group(1) if tag else "?",
            "name": html.unescape(nm.group(1)) if nm else "",
            "props": props,
        })
    return out


def parametric_report(params, feats):
    """각 지오메트리 feature 가 어떤 전역 매개변수를 참조하는지 역추적한다."""
    names = sorted(params, key=len, reverse=True)
    used = {}
    for f in feats:
        refs = set()
        for v in f["props"].values():
            for n in names:
                if re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n), v):
                    refs.add(n)
        if refs:
            used[f["tag"]] = sorted(refs)
    return used


def materials(d):
    out = []
    for m in re.finditer(r'<Material\b[^>]*>', d):
        nm = re.search(r'name="([^"]*)"', m.group(0))
        tag = re.search(r'tag="([^"]+)"', m.group(0))
        out.append({"tag": tag.group(1) if tag else "?",
                    "name": html.unescape(nm.group(1)) if nm else ""})
    return out


def physics(d):
    out = []
    for m in re.finditer(r'<Physics\b[^>]*>', d):
        op = re.search(r'op="([^"]+)"', m.group(0))
        tag = re.search(r'tag="([^"]+)"', m.group(0))
        nm = re.search(r'name="([^"]*)"', m.group(0))
        out.append({"op": op.group(1) if op else "?",
                    "tag": tag.group(1) if tag else "?",
                    "name": html.unescape(nm.group(1)) if nm else ""})
    return out


def bcs(d):
    """경계조건 feature 와 핵심 설정값."""
    KEYS = {"T0", "h", "q0", "Text", "HeatFluxType", "HeatTransferCoefficientType",
            "Tinit", "U", "Q0", "P0"}
    out = []
    starts = [m.start() for m in re.finditer(r"<PhysicsFeature\b", d)] + [len(d)]
    for i in range(len(starts) - 1):
        blk = d[starts[i]:starts[i + 1]]
        head = blk[:blk.find(">") + 1]
        op = re.search(r'op="([^"]+)"', head)
        tag = re.search(r'tag="([^"]+)"', head)
        nm = re.search(r'name="([^"]*)"', head)
        vals = {}
        for p in re.finditer(r'<param T="\d+" param="([^"]+)" value="([^"]*)"', blk):
            if p.group(1) in KEYS:
                v = html.unescape(p.group(2))
                mm = re.match(r"^\d+\|1,'(.*)'$", v)
                vals[p.group(1)] = mm.group(1) if mm else v
        out.append({"op": op.group(1) if op else "?",
                    "tag": tag.group(1) if tag else "?",
                    "name": html.unescape(nm.group(1)) if nm else "",
                    "values": vals})
    return out


def studies(d):
    st = re.findall(r'<Study tag="([^"]+)"', d)
    sf = re.findall(r'<StudyFeature op="([^"]+)" tag="([^"]+)"', d)
    return {"studies": st, "steps": sf}


def analyze(path):
    d, names = read_dmodel(path)
    params = parameters(d)
    feats = geom_features(d)
    used = parametric_report(params, feats)
    mesh_entries = [n for n in names if n.endswith(".mphbin")]
    return {
        "file": str(path),
        "entries": len(names),
        "mesh_binaries": len(mesh_entries),
        "parameters": params,
        "geometry_features": [{k: f[k] for k in ("op", "tag", "name")} for f in feats],
        "parametric_features": used,
        "materials": materials(d),
        "physics": physics(d),
        "boundary_conditions": [b for b in bcs(d) if b["values"]],
        **studies(d),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mph")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyze(a.mph)

    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print(f"파일: {r['file']}")
    print(f"  ZIP 엔트리 {r['entries']}개 / 메시·형상 바이너리 {r['mesh_binaries']}개")
    print()
    print(f"=== 전역 매개변수 {len(r['parameters'])}개 ===")
    for k, v in r["parameters"].items():
        print(f"   {k:18s} = {v}")
    print()
    print(f"=== 지오메트리 feature {len(r['geometry_features'])}개 ===")
    ops = {}
    for f in r["geometry_features"]:
        ops[f["op"]] = ops.get(f["op"], 0) + 1
    print("   " + ", ".join(f"{k}x{v}" for k, v in sorted(ops.items())))
    print()
    print("=== 매개변수를 참조하는 feature (파라메트릭 판정) ===")
    if not r["parametric_features"]:
        print("   없음 -> 형상이 매개변수를 따라가지 않는다. 자동화 불가.")
    for tag, refs in r["parametric_features"].items():
        nm = next((f["name"] for f in r["geometry_features"] if f["tag"] == tag), "")
        print(f"   {tag:10s} {nm[:26]:28s} <- {', '.join(refs)}")
    print()
    print("=== 재료 ===")
    for m in r["materials"]:
        print(f"   {m['tag']:8s} {m['name']}")
    print()
    print("=== 물리 / 경계조건 ===")
    for p in r["physics"]:
        print(f"   {p['op']} (tag={p['tag']}) {p['name']}")
    for b in r["boundary_conditions"]:
        print(f"   {b['op']:26s} {b['name'][:18]:20s} {b['values']}")
    print()
    print(f"=== 스터디 ===\n   {r['studies']}  steps={r['steps']}")
    print()
    if not r["parametric_features"]:
        print("판정: 자동화 불가 (형상이 매개변수에 종속되지 않음)")
        return 1
    print("판정: 파라메트릭 - -pname/-plist 주입으로 형상 재빌드 가능")
    return 0


if __name__ == "__main__":
    sys.exit(main())
