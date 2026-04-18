import sys
import struct
from fontTools.ttLib import TTFont

# tt = TTFont('/Users/toshi/Library/Application Support/Glyphs 3/Temp/EisaiSerif260320-Expanded.otf')
tt = TTFont('/Users/toshi/Github repos/BubbleKern2/BubbleKern/BubbleKernTest-Regular.otf')
print("Tables in font:", tt.keys())
#tt.close()

if "BBLH" not in tt.keys():
	print("No BBLH table found.")
	sys.exit(1)

data = tt["BBLH"].data
print("BBLH table size:", len(data))

# Parse header: >H version, >I glyphCount
pos = 0
if len(data) < 6:
	print("BBLH too small to contain header")
	sys.exit(1)

version, = struct.unpack_from(">H", data, pos); pos += 2
glyphCount, = struct.unpack_from(">I", data, pos); pos += 4
print("version:", version, "glyphCount:", glyphCount)

glyph_order = tt.getGlyphOrder()
print("Glyph order length:", len(glyph_order))

# Iterate glyph entries and print summary for each glyph
for i, glyph_name in enumerate(glyph_order):
	if pos >= len(data):
		print("Reached end of data unexpectedly at glyph index", i)
		break
	presence, = struct.unpack_from(">B", data, pos); pos += 1
	if presence == 0:
		# no data
		print(f"{i:4d}: {glyph_name}: (no data)")
		continue
	# read set1
	if pos + 2 > len(data):
		print("Truncated reading n1 at glyph", glyph_name); break
	n1, = struct.unpack_from(">H", data, pos); pos += 2
	coords1 = []
	for _ in range(n1):
		if pos + 8 > len(data):
			print("Truncated coords1 at glyph", glyph_name); break
		x, y = struct.unpack_from(">ii", data, pos); pos += 8
		coords1.append((x, y))
	# read set2
	if pos + 2 > len(data):
		print("Truncated reading n2 at glyph", glyph_name); break
	n2, = struct.unpack_from(">H", data, pos); pos += 2
	coords2 = []
	for _ in range(n2):
		if pos + 8 > len(data):
			print("Truncated coords2 at glyph", glyph_name); break
		x, y = struct.unpack_from(">ii", data, pos); pos += 8
		coords2.append((x, y))

	print(f"{i:4d}: {glyph_name}: set1={n1}, set2={n2}")
	# optionally print coords
	print("  set1:", coords1)
	print("  set2:", coords2)