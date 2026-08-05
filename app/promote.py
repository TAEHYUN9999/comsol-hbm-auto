# 골든 승격 - 사용자가 명시적으로 실행하는 것. 탐색기가 스스로 부르지 않는다
"""
사용: python promote.py G017_...

fbuf 규칙과 동일하게 골든 승격은 확인 사항이다. 메시 게이트를 통과하지 못한
세대는 승격할 수 없다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generation  # noqa: E402


def main():
    if len(sys.argv) != 2:
        cur = generation.current_golden()
        print(f"현재 골든: {cur or '(없음)'}")
        print("\n승격 가능한 세대 (게이트 통과분):")
        for g in generation.all_generations():
            if g["valid"]:
                print(f"  {g['name']:52s} R_th={g['result'].get('R_th', float('nan')):9.5f}")
        print("\n사용: python promote.py <세대이름>")
        return 1

    name = sys.argv[1]
    old = generation.current_golden()
    generation.promote(name)
    print(f"골든 승격: {old or '(없음)'} -> {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
