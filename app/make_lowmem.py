# 저메모리(노트북) 변형 .mph 를 만든다 - 이산화 차수를 2차에서 1차로 낮춘다
"""
왜 필요한가:
  원본 모델은 온도장을 2차식 라그랑지로 푼다. 사면체 P2 는 P1 대비 자유도가
  약 7.5배라, 실측에서 자유도 884,367 / 물리 메모리 16.5 GB 를 썼다.
  RAM 16 GB 노트북(WSL2 는 그중 일부만 할당)에서는 들어가지 않는다.

  1차로 낮추면 자유도가 약 118,000 으로 떨어진다. 3D 직접 솔버 메모리는
  자유도에 초선형으로 붙으므로 1~2 GB 수준이 된다.

정확도:
  정상상태 열전도는 해가 매끄러워 P1 으로도 충분한 경우가 많다.
  다만 "충분하다"를 가정하지 말고 메시 수렴 게이트로 확인할 것.
  P1 은 같은 메시에서 P2 보다 부정확하므로, 필요하면 메시를 조밀하게 해서 보상한다.

지오메트리 편집과 다른 점 (중요):
  지오메트리는 buildStatus 캐시가 있어 XML 직접 편집이 무시된다(실측).
  이산화는 캐시가 없고 매 실행마다 방정식을 새로 컴파일하므로 편집이 반영된다.
  다만 이 역시 검증 없이 믿지 말 것 - 실행 로그의 자유도가
  884,367 그대로면 반영이 안 된 것이고, 12만 근처면 반영된 것이다.

사용:
  python make_lowmem.py <원본.mph> <출력.mph>
  python make_lowmem.py <원본.mph> <출력.mph> --order 1
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

FIELD = "order_temperature"


def patch_xml(text: str, new_order: str):
    """<param param="order_temperature" value="N|1,'X'"> 의 X 를 바꾼다."""
    # 이미 목표 차수인 항목은 건드리지 않는다. 정체를 모르는 값을 바꾸지 않기 위함.
    # (실측: savepoint 의 Discretization/disc1 에 order_temperature 가 2건 있고
    #  하나는 원래 '1' 이었다. 전부 치환하면 그 항목까지 손대게 된다)
    pat = re.compile(
        r'(<param T="\d+" param="%s" value="(\d+)\|1,\')(\d+)(\'")' % FIELD)
    found = []

    def repl(m):
        cur = m.group(3)
        if cur == new_order:
            return m.group(0)          # 이미 목표값 - 원문 유지
        found.append(cur)
        return m.group(1) + new_order + m.group(4)

    out = pat.sub(repl, text)
    return out, found


def patch_inner_zip(data: bytes, new_order: str, tmpdir: Path):
    src, dst = tmpdir / "in.zip", tmpdir / "out.zip"
    src.write_bytes(data)
    found = []
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename.endswith("dmodel.xml"):
                txt, f = patch_xml(blob.decode("utf-8"), new_order)
                blob = txt.encode("utf-8")
                found += f
            zout.writestr(info, blob)
    out = dst.read_bytes()
    src.unlink(); dst.unlink()
    return out, found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--order", default="1", choices=["1", "2"],
                    help="이산화 차수 (1=선형/저메모리, 2=원본)")
    a = ap.parse_args()

    src, out = Path(a.source), Path(a.output)
    if not src.exists():
        raise SystemExit(f"원본 없음: {src}")
    if out.exists():
        raise SystemExit(f"출력이 이미 있다(덮어쓰지 않음): {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = out.parent / "_tmp_lowmem"
    tmpdir.mkdir(exist_ok=True)

    print(f"원본 : {src}  ({src.stat().st_size/1e6:.1f} MB)")
    print(f"이산화 차수 -> {a.order} ({'선형/저메모리' if a.order == '1' else '2차/원본'})")
    print()

    found = []
    n = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename == "dmodel.xml":
                txt, f = patch_xml(blob.decode("utf-8"), a.order)
                blob = txt.encode("utf-8")
                found += f
                if f:
                    print(f"  수정: {info.filename}  {FIELD} {f} -> {a.order}")
            elif info.filename.endswith(".zip"):
                blob, f = patch_inner_zip(blob, a.order, tmpdir)
                found += f
                if f:
                    print(f"  수정: {info.filename} (중첩)  {FIELD} {f} -> {a.order}")
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, blob)
            n += 1

    shutil.rmtree(tmpdir, ignore_errors=True)
    print()
    print(f"엔트리 {n}개 기록, {FIELD} 치환 {len(found)}건 (원래 값 {set(found) or '-'})")
    print(f"출력 : {out}  ({out.stat().st_size/1e6:.1f} MB)")

    if not found:
        print(f"\n실패: {FIELD} 를 찾지 못했다. 이 모델은 이 방법으로 낮출 수 없다.")
        print("      GUI 에서 물리현상 > 이산화 > 온도 를 직접 바꿀 것.")
        return 1

    print()
    print("검증 방법 (반드시 확인할 것):")
    print("  실행 로그의 '풀이되는 자유도 수' 를 본다.")
    print("    원본(2차) 기준값과 같으면 -> 반영 안 됨. GUI 로 바꿀 것.")
    print("    7~8배 줄었으면       -> 반영됨.")
    print("  solve_comsol.sh 가 이 대조를 자동으로 해준다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
