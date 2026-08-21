# encoding: utf-8
"""Writing the bubbles into an exported font, as a custom `BBLH` table.

A `.otf` carries no bubbles, so a font exported from a file that has them
loses the thing this plugin is for. This puts them back: `collectBBLHData`
reads what every glyph resolves to, and `writeFontWithBBLH` saves a font with
a `BBLH` table holding it.
"""

import traceback

from AppKit import NSBezierPath

from BKCommonLogic import getFinalBubble, log, show_alert




# BBLH TABLE EXPORT LOGIC (Written entirely by AI so far)

"""
Custom BBLH Table for FontTools
Stores glyph names with up to two sets of node coordinates.
Format: version (>H), glyphCount (>I), then for each glyph:
  presence (>B), if present: n1 (>H), coords1 (n1 x >ii), n2 (>H), coords2 (n2 x >ii)
"""



def _normalize_nodes_for_export(rawNodes:NSBezierPath, isRight:bool=True, width:float=None):
	if rawNodes is None:
		return []
	
	# extract nodes from NSBezierPath
	nodesTemp = []
	for i in range(rawNodes.elementCount()):
		element = rawNodes.elementAtIndex_associatedPoints_(i) # tuple of node type and node(s)
		nodesTemp.append(element[1][0])

	nodes = [(int(round(n.x)), int(round(n.y))) for n in nodesTemp]

	return nodes


def collectBBLHData(font=None, masterId=None) -> dict:
	"""
	Collect BubbleKern node data for a master and return it as:
	{
		"A": [[(x, y), ...], [(x, y), ...]],
		"B": [[...], [...]],
	}

	Only glyphs that have at least one bubble side are included.
	"""
	try:
		f = font

		result = {}
		for g in f.glyphs:
			try:
				layer = g.layers[masterId]
			except Exception:
				continue
			wid = layer.width
			# maybe should improve bubble generation logic to incorporate components and references,
			# so that the exported BBLH data is more complete and accurate;
			# currently only the nodes directly on the master layer are exported,
			# which may miss some bubbles if they are built from components or references
			left_nodes = _normalize_nodes_for_export(getFinalBubble( layer, isLeft = True ), False, None)
			right_nodes = _normalize_nodes_for_export(getFinalBubble( layer, isLeft = False ), True, wid)

			result[g.name] = [left_nodes, right_nodes]
		
		return result
	except Exception:
		log(f'collectBBLHData error: {traceback.format_exc()}', error=True)
		return {}



# to be run from BKKerner
def writeFontWithBBLH(folderPath, font=None): # want to use this name later
	"""
	Add BBLH table to a font.

	bblh_data: Dict with glyph names as keys and 
				((coord_set1), (coord_set2)) as values.
				Use empty tuples () for missing coordinate sets.
	Example:
		bblh_data = {
			'A': (((0, 1), (125, 699)), ((639, 0), (501, 696))),
			'R': ((), ((412, -8), (520, 613), (520, 800))),
			'T': (((109, -16), (0, 611), (0, 800)), ((412, -8), (520, 613), (520, 800))),
		}
		add_bblh_table('your_font.ttf', bblh_data, 'your_font_with_bblh.ttf')
	"""
	try:
		from fontTools.ttLib import TTFont
		from fontTools.ttLib.tables import DefaultTable
		import io
		from struct import pack, unpack
	except ImportError:
		show_alert(
			"FontTools is required.",
			"Install it in Glyphs Python with: pip install fonttools",
			cancel=False,
		)
		return None
	
	# make a class to build BBLH table data
	class table_B_B_L_H(DefaultTable.DefaultTable):
		"""Custom BBLH table class for FontTools."""
	
		def __init__(self, tag=None):
			super().__init__(tag)
			self.glyphs = {}  # {glyph_name: ((coords_set1), (coords_set2))}
		
		def compile(self, ttFont):
			"""Compile the BBLH table to binary data."""
			data = io.BytesIO()
			
			# Write version (uint16)
			data.write(pack('>H', 1))  # Version 1.0
			
			# Get glyph order from font
			glyphOrder = ttFont.getGlyphOrder()
			
			# Write number of glyphs (uint32)
			data.write(pack('>I', len(glyphOrder)))
			
			# Write glyph entries in glyph order
			for glyph_name in glyphOrder:
				if glyph_name not in self.glyphs:
					# No data for this glyph
					data.write(pack('>B', 0))  # presence flag = 0
				else:
					# Has data
					data.write(pack('>B', 1))  # presence flag = 1
					
					coord_set1, coord_set2 = self.glyphs[glyph_name]
					
					# Write set1 count and coordinates
					data.write(pack('>H', len(coord_set1)))
					for x, y in coord_set1:
						data.write(pack('>ii', x, y))  # Signed 32-bit integers
					
					# Write set2 count and coordinates
					data.write(pack('>H', len(coord_set2)))
					for x, y in coord_set2:
						data.write(pack('>ii', x, y))
			
			return data.getvalue()
		
		def decompile(self, data, ttFont):
			"""Decompile binary data into the BBLH table."""
			reader = io.BytesIO(data)
			glyphOrder = ttFont.getGlyphOrder()
			
			# Read version
			version_bytes = reader.read(2)
			if len(version_bytes) < 2:
				return
			version = unpack('>H', version_bytes)[0]
			
			# Read number of glyphs
			count_bytes = reader.read(4)
			if len(count_bytes) < 4:
				return
			glyph_count = unpack('>I', count_bytes)[0]
			
			self.glyphs = {}
			
			for glyph_idx in range(min(glyph_count, len(glyphOrder))):
				# Read presence flag
				presence_bytes = reader.read(1)
				if len(presence_bytes) < 1:
					break
				presence = unpack('>B', presence_bytes)[0]
				
				if presence == 0:
					# No data for this glyph
					continue
				
				glyph_name = glyphOrder[glyph_idx]
				
				# Read set1 count and coordinates
				n1_bytes = reader.read(2)
				if len(n1_bytes) < 2:
					break
				n1 = unpack('>H', n1_bytes)[0]
				
				coord_set1 = []
				for _ in range(n1):
					coord_bytes = reader.read(8)
					if len(coord_bytes) < 8:
						break
					x, y = unpack('>ii', coord_bytes)
					coord_set1.append((x, y))
				
				# Read set2 count and coordinates
				n2_bytes = reader.read(2)
				if len(n2_bytes) < 2:
					break
				n2 = unpack('>H', n2_bytes)[0]
				
				coord_set2 = []
				for _ in range(n2):
					coord_bytes = reader.read(8)
					if len(coord_bytes) < 8:
						break
					x, y = unpack('>ii', coord_bytes)
					coord_set2.append((x, y))
				
				self.glyphs[glyph_name] = (tuple(coord_set1), tuple(coord_set2))
		
		def toXML(self, writer, ttFont):
			"""Convert BBLH table to XML."""
			writer.begintag('BBLH')
			writer.newline()
			
			glyphOrder = ttFont.getGlyphOrder()
			
			for glyph_name in glyphOrder:
				if glyph_name not in self.glyphs:
					continue
				
				set1, set2 = self.glyphs[glyph_name]
				writer.simpletag('glyph', name=glyph_name)
				writer.newline()
				
				# Write first set
				writer.begintag('set', index='1')
				writer.newline()
				for x, y in set1:
					writer.simpletag('coord', x=x, y=y)
					writer.newline()
				writer.endtag('set')
				writer.newline()
				
				# Write second set
				writer.begintag('set', index='2')
				writer.newline()
				for x, y in set2:
					writer.simpletag('coord', x=x, y=y)
					writer.newline()
				writer.endtag('set')
				writer.newline()
				
				writer.endtag('glyph')
				writer.newline()
			
			writer.endtag('BBLH')
			writer.newline()
		
		def fromXML(self, name, attrs, parent):
			"""Parse BBLH table from XML."""
			if name == 'BBLH':
				self.glyphs = {}
			elif name == 'glyph':
				self._current_glyph = attrs['name']
				self._current_sets = [[], []]
			elif name == 'set':
				self._current_set_idx = int(attrs['index']) - 1
			elif name == 'coord':
				x = int(attrs['x'])
				y = int(attrs['y'])
				self._current_sets[self._current_set_idx].append((x, y))

	# end of BBLH class definition

	if font is None:
		return None

	exportedPaths = []

	for m in font.masters:
		# log(f'Processing master: {m.name}')
		# check for valid instance
		insFound = False
		for ins in font.instances:
			if ins.active and ins.axes == m.axes:
				insFound = True
				break
		if insFound is False:
			return None

		# gather bblh data
		bblhData = collectBBLHData(font=font, masterId=m.id)
		if not bblhData:
			return None
		
		# generate instance in the inputFontPath
		ins.generate(fontPath=folderPath)
		fontFileName = ins.lastExportedFilePath.split('/')[-1]
		outputFontPath = folderPath + '/' + fontFileName # path to the font file


		bubbledFont = TTFont(outputFontPath)
		
		# Create BBLH table
		bblh_table = table_B_B_L_H('BBLH')
		bblh_table.glyphs = bblhData
		
		# Add to font
		bubbledFont['BBLH'] = bblh_table
		
		# Save
		bubbledFont.save(outputFontPath)
		exportedPaths.append(outputFontPath)
	
	log('writeFontWithBBLH completed successfully.')
	return exportedPaths
