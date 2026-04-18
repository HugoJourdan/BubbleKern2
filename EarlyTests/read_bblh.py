"""
Standalone BBLH table reader.
Usage: python read_bblh.py /path/to/font.otf
"""

import sys
import struct
from fontTools.ttLib import TTFont


def read_bblh_table(font_path):
    tt = TTFont(font_path)
    print(f"Tables in font: {list(tt.keys())}")

    if "BBLH" not in tt:
        print("No BBLH table found")
        tt.close()
        return

    data = tt["BBLH"].data
    print(f"BBLH table size: {len(data)}")

    offset = 0
    version, glyph_count = struct.unpack_from(">HI", data, offset)
    offset += 6
    print(f"version: {version} glyphCount: {glyph_count}")

    glyph_order = tt.getGlyphOrder()
    print(f"Glyph order length: {len(glyph_order)}")

    for i, name in enumerate(glyph_order):
        presence = struct.unpack_from(">B", data, offset)[0]
        offset += 1

        if presence == 0:
            print(f"  {i:3d}: {name}: (no data)")
        else:
            s1 = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            set1 = []
            for _ in range(s1):
                x, y = struct.unpack_from(">ii", data, offset)
                offset += 8
                set1.append((x, y))

            s2 = struct.unpack_from(">H", data, offset)[0]
            offset += 2
            print(f"  {i:3d}: {name}: set1={s1}, set2={s2}")
            set2 = []
            for _ in range(s2):
                x, y = struct.unpack_from(">ii", data, offset)
                offset += 8
                set2.append((x, y))
            print(f"  set1: {set1}")
            print(f"  set2: {set2}")

    tt.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python read_bblh.py /path/to/font.otf")
        sys.exit(1)
    read_bblh_table(sys.argv[1])
