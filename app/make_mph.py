# 골든 형상을 반영한 .mph 를 원본에서 만들어낸다 (COMSOL 실행 없이)
"""
왜 이게 되는가:
  원본 모델의 히트싱크 지오메트리는 CAD 임포트가 아니라 완전 파라메트릭이다.
    blk26 (베이스)  size = (dram_die_size, dram_die_size, t_base),  pos.z = z_hs
    cyl26 (핀)      r = r_pin,  h = h_pin,  pos = (x0, y0, z_hs + t_base)
    arr13 (배열)    size = (n, n, 1),  displ = (p, p, 0)
  x0, y0 는 n, p 의 수식이라 자동으로 따라온다.
  따라서 전역 매개변수 3개만 바꾸면 GUI 에서 Build All 로 그대로 재빌드된다.

.mph 는 ZIP 이고 매개변수는 두 곳에 중복 저장되어 있다:
  dmodel.xml                 (최상위 모델 트리)
  savepoint1/model.zip 안의 dmodel.xml
둘 다 고쳐야 한다.

주의: 파일 안의 지오메트리/메시/해는 옛 형상 그대로다. 열어서
      Geometry > Build All -> Mesh > Build All -> Study > Compute 를 실행해야 한다.
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

# 이름 -> (원본 expr, 새 expr)
DEFAULT_EDITS = {
    "r_pin": ("75[um]", "78[um]"),
    "p":     ("301[um]", "206[um]"),
    "n":     ("4", "6"),
}


def patch_xml(text: str, edits: dict) -> tuple[str, dict]:
    """<expressions T="31" name="X" expr="..."> 의 expr 만 바꾼다."""
    counts = {}
    for name, (old, new) in edits.items():
        pat = re.compile(
            r'(<expressions T="31" name="%s" expr=")([^"]*)(")' % re.escape(name))

        def repl(m, name=name, old=old, new=new):
            cur = m.group(2)
            if cur != old:
                raise ValueError(
                    f"{name}: 원본 값이 예상과 다르다 (기대 {old!r}, 실제 {cur!r}). "
                    f"다른 .mph 이거나 이미 수정된 파일이다.")
            counts[name] = counts.get(name, 0) + 1
            return m.group(1) + new + m.group(3)

        text = pat.sub(repl, text)
    return text, counts


def patch_inner_zip(data: bytes, edits: dict, tmpdir: Path) -> tuple[bytes, dict]:
    """savepoint1/model.zip 처럼 중첩된 zip 안의 dmodel.xml 을 고친다."""
    src = tmpdir / "inner_in.zip"
    dst = tmpdir / "inner_out.zip"
    src.write_bytes(data)
    total = {}
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename.endswith("dmodel.xml"):
                txt, c = patch_xml(blob.decode("utf-8"), edits)
                blob = txt.encode("utf-8")
                for k, v in c.items():
                    total[k] = total.get(k, 0) + v
            zout.writestr(info, blob)
    out = dst.read_bytes()
    src.unlink(); dst.unlink()
    return out, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="원본 .mph")
    ap.add_argument("output", help="새로 만들 .mph")
    ap.add_argument("--set", nargs="*", default=None,
                    help="name=old:new 형식으로 덮어쓰기 (예: n=4:6)")
    args = ap.parse_args()

    edits = dict(DEFAULT_EDITS)
    if args.set:
        edits = {}
        for s in args.set:
            name, _, pair = s.partition("=")
            old, _, new = pair.partition(":")
            edits[name] = (old, new)

    src = Path(args.source)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = out.parent / "_tmp_mph"
    tmpdir.mkdir(exist_ok=True)

    print(f"원본: {src}  ({src.stat().st_size/1e6:.1f} MB)")
    print("매개변수 변경:")
    for k, (o, n) in edits.items():
        print(f"   {k:8s} {o:>10}  ->  {n}")
    print()

    total = {}
    n_entries = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename == "dmodel.xml":
                txt, c = patch_xml(blob.decode("utf-8"), edits)
                blob = txt.encode("utf-8")
                print(f"  수정: {info.filename}  {c}")
            elif info.filename.endswith(".zip"):
                blob, c = patch_inner_zip(blob, edits, tmpdir)
                if c:
                    print(f"  수정: {info.filename} (중첩 zip 내부)  {c}")
            else:
                c = {}
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
            # 원본 엔트리 순서/압축방식을 유지한다
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, blob)
            n_entries += 1

    shutil.rmtree(tmpdir, ignore_errors=True)
    print()
    print(f"엔트리 {n_entries}개 기록, 총 치환 {total}")
    print(f"출력: {out}  ({out.stat().st_size/1e6:.1f} MB)")

    missing = [k for k in edits if total.get(k, 0) < 2]
    if missing:
        print(f"\n경고: {missing} 의 치환이 2곳(최상위+savepoint) 미만이다. 확인 필요.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
