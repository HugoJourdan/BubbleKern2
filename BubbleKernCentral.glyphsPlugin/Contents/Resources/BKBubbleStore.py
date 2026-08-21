# encoding: utf-8
"""What a run puts in the font: the bubbles, and the kerning they imply.

None of this needs a canvas. It reads and writes `userData` on layers, asks
`BKAutoBubble` to measure, and reports counts back; the tool wraps it in undo
groups and redraws, and the Kerner calls the same functions without a tool
being loaded at all.
"""

import traceback

from Cocoa import NSPoint
from GlyphsApp import Glyphs, GSControlLayer, GSLayer

import BKAutoBubble as auto
import BKPreview as preview
from BKSide import LEFT, RIGHT, SIDES, of
from BKCommonLogic import (getFinalBubble, getKernValue, isBlankWall,
	isMirrored, isReferenceValid, log, mergeableComposite, recordBox,
	tempToUserNodeX)

# font.userData: EVERY PAIR THE PREVIEW WROTE, SO IT CAN ALWAYS BE TAKEN BACK
PreviewKerningKey = 'BubbleKernPreviewKerning'


def infoForLayer(layer):  # RETURNS referL, referR
	userData = layer.userData
	referL = userData.get(LEFT.key('Refer'), None)
	if isinstance(referL, str) and len(referL) == 0:
		referL = None
	if referL and not isReferenceValid(layer, LEFT):
		referL = None
	referR = userData.get(RIGHT.key('Refer'), None)
	if isinstance(referR, str) and len(referR) == 0:
		referR = None
	if referR and not isReferenceValid(layer, RIGHT):
		referR = None
	return referL, referR


def nodesFromFinalBubble(layer, isLeft):
	"""The wall this layer RESOLVES to, in stored form. -> [(x, y)] or None

	A composite has no wall of its own: it is the merge of its components.
	This is that merge, written the way userData writes one, which is what
	both decomposing and loading the handles need.
	"""
	try:
		path = getFinalBubble(layer, isLeft)
		if path is None or path.elementCount() == 0:
			return None
		m = layer.associatedFontMaster()
		width = 0 if isLeft else layer.width
		nodes = []
		for index in range(path.elementCount()):
			n = path.elementAtIndex_associatedPoints_(index)[1][0]
			nodes.append((int(round(tempToUserNodeX(
					n.x - width, n.y, m.italicAngle, m.xHeight))), int(round(n.y))))
		return nodes or None
	except Exception:
		log(f'nodesFromFinalBubble error: {traceback.format_exc()}', error=True)
		return None


def tabLayers(tab):
	"""Everything in a tab, in order, control layers and all. -> iterator

	`tab.layers` HAS NO `__len__` - it raises - but it does have `__iter__`, and
	the proxy iterates. Never walk it by index against a sentinel. See CLAUDE.md.
	"""
	try:
		yield from tab.layers
	except Exception:
		log(f'tabLayers error: {traceback.format_exc()}', error=True)


def tabIndexOf(tab, layer):  # WHERE THIS LAYER SITS IN THE TAB, OR None
	# THE CURSOR IS ASKED FIRST BECAUSE A REPEATED GLYPH IS THE SAME GSLayer
	# OBJECT AT EVERY OCCURRENCE, AND ONLY THE CURSOR TELLS THEM APART.
	try:
		cursor = tab.textCursor
		if cursor is not None and cursor >= 0 and tab.layers[cursor] == layer:
			return cursor
	except Exception:
		pass
	for position, candidate in enumerate(tabLayers(tab)):
		if candidate == layer:
			return position
	return None


def gridFor(layer):  # ROW INCREMENT FOR THIS LAYER'S FONT; 0 = NO GRID
	# READS THE FONT PARAMETER AND NSUserDefaults, NOT Glyphs.font, WHICH
	# WOULD BE AN XPC ROUND TRIP ON EVERY DRAGGED PIXEL.
	try:
		return auto.resolve_grid(layer.font() if layer else None,
			layer.associatedFontMaster() if layer else None)
	except Exception:
		log(f'gridFor error: {traceback.format_exc()}', error=True)
		return 0


def snapNode(node, layer, isRight):  # SNAP ONE LIVE NODE IN PLACE
	try:
		grid = gridFor(layer)
		if not grid:
			return
		x, y = node.pos.x, node.pos.y
		y = round(y / float(grid)) * grid
		node.pos = NSPoint(round(x), round(y))
	except Exception:
		log(f'snapNode error: {traceback.format_exc()}', error=True)


def snapStored(nodes, side, grid):  # SNAP A LIST OF STORED (x, y)
	# auto.snap_points WORKS IN WALL SPACE, WHERE A SMALLER X IS FURTHER OUT
	# INTO THE WHITESPACE. THAT IS THE STORED X ON THE LEFT AND ITS NEGATION
	# ON THE RIGHT, SO THE RIGHT SIDE FLIPS EITHER SIDE OF THE CALL.
	def flipped(points):
		return [(-x, y) for x, y in points] if not side.isLeft else points

	return flipped(auto.snap_points(flipped(nodes), grid))


def mergeFromComponents(layer, side):
	"""Leave a composite to its components instead of drawing it a wall.

	A composite that carries a wall of its own stops following the glyphs it is
	made of, which is the whole point of a composite: edit the circumflex and
	every glyph wearing one should move with it.
	-> True when the layer was cleared and left to the merge.
	"""
	try:
		if layer.userData[side.key('Refer')]:
			return False  # pointed elsewhere by hand; not ours to clear
		if not mergeableComposite(layer):
			return False
		glyph = layer.parent
		glyph.beginUndo()
		try:
			for key in (side.key('Nodes'), side.key('Box')):
				if layer.userData[key]:
					del layer.userData[key]
		finally:
			glyph.endUndo()
		# THE COMPONENTS MAY HAVE NOTHING TO LEND. A composite of glyphs
		# nobody has drawn a bubble for merges to the line on the origin,
		# which is no wall at all - better to draw this one after all.
		# Asked AFTER clearing, or the answer is the layer's own nodes.
		borrowed = nodesFromFinalBubble(layer, side.isLeft)
		return bool(borrowed) and not isBlankWall(borrowed)
	except Exception:
		log(f'mergeFromComponents error: {traceback.format_exc()}', error=True)
		return False


def writeBubble(layer, side, nodes=None, refer=None):
	# ONE SIDE OF ONE LAYER, AS ONE UNDO STEP. NODES AND A REFERENCE ARE
	# ALTERNATIVES: gatherBubbleInfo READS THE REFERENCE FIRST, SO LEAVING
	# THE OTHER BEHIND WOULD LEAVE DEAD DATA IN THE FILE.
	nodesKey, referKey = side.key('Nodes'), side.key('Refer')
	mirrorKey = side.key('Mirror')
	glyph = layer.parent
	glyph.beginUndo()
	try:
		if nodes is not None:
			layer.userData[nodesKey] = nodes
			recordBox(layer, side)
			if layer.userData[referKey]:
				del layer.userData[referKey]
			if layer.userData[mirrorKey]:
				del layer.userData[mirrorKey]
		elif refer is not None:
			layer.userData[referKey] = refer
			if layer.userData[mirrorKey]:
				del layer.userData[mirrorKey]
			if not isReferenceValid(layer, side):  # WOULD BE A CYCLE
				del layer.userData[referKey]
				return False
			if layer.userData[nodesKey]:
				del layer.userData[nodesKey]
	finally:
		glyph.endUndo()
	return True


def lockedSides(layer):  # (LEFT, RIGHT) SIDES THAT ARE NOT EDITED HERE
	referL, referR = infoForLayer(layer)
	return tuple(borrowed or isMirrored(layer, side.isLeft)
		for borrowed, side in zip((bool(referL), bool(referR)), SIDES))


def previewPairs(tab):  # ADJACENT PAIRS OF REAL LAYERS IN THE TAB
	pairs, previous = [], None
	for layer in tabLayers(tab):
		if layer is None or isinstance(layer, GSControlLayer) or layer.name is None:
			previous = None  # a line break ends the run
			continue
		if previous is not None:
			pairs.append((previous, layer))
		previous = layer
	return pairs


def effectiveKerning(leftLayer, rightLayer, font, masterId):
	# WHAT THE FONT ALREADY SAYS ABOUT THIS PAIR, OR None IF IT SAYS NOTHING.
	# ASKED THROUGH THE LAYERS BECAUSE THAT RESOLVES GROUPS: kerningForPair
	# BY GLYPH NAME REPORTS None FOR A PAIR KERNED THROUGH A CLASS, AND WE
	# WOULD HAPPILY WRITE AN EXCEPTION OVER SOMEBODY'S CLASS.
	# UNDEFINED COMES BACK AS A 2**63 SENTINEL, NOT None.
	# AN EXPLICIT ZERO IS A DECISION AND COUNTS AS DEFINED.
	try:
		value = leftLayer.nextKerningForLayer_direction_(rightLayer, 0)
		if value is None or abs(value) > 100000:
			return None
		return value
	except Exception:
		return font.kerningForPair(masterId, leftLayer.parent.name, rightLayer.parent.name)


def clearPreviewKerning(font=None):
	try:
		font = font if font is not None else Glyphs.font
		if font is None:
			return 0
		written = font.userData[PreviewKerningKey]
		if not written:
			return 0
		removed = 0
		for entry in list(written):
			try:
				font.removeKerningForPair(str(entry[0]), str(entry[1]), str(entry[2]))
				removed += 1
			except Exception:
				pass
		del font.userData[PreviewKerningKey]
		return removed
	except Exception:
		log(f'clearPreviewKerning error: {traceback.format_exc()}', error=True)
		return 0


def applyPreviewKerning(font=None):
	try:
		font = font if font is not None else Glyphs.font
		if font is None:
			return
		clearPreviewKerning(font)  # always from a clean slate
		tab = font.currentTab
		if tab is None:
			return
		masterId = font.selectedFontMaster.id
		written = []
		for leftLayer, rightLayer in previewPairs(tab):
			if effectiveKerning(leftLayer, rightLayer, font, masterId) is not None:
				continue  # the font already has an opinion; leave it alone
			wallR = getFinalBubble(leftLayer, isLeft=False)
			wallL = getFinalBubble(rightLayer, isLeft=True)
			if wallR is None or wallL is None:
				continue
			value, row = getKernValue(wallR, wallL, int(leftLayer.width), withRow=True,
				space=auto.fit_space(font, leftLayer.associatedFontMaster()))
			if row is None or value == float('inf'):
				continue
			kern = -int(round(value))
			if kern == 0:
				continue
			left, right = leftLayer.parent.name, rightLayer.parent.name
			font.setKerningForPair(masterId, left, right, kern)
			written.append([masterId, left, right])
		if written:
			font.userData[PreviewKerningKey] = written
	except Exception:
		log(f'applyPreviewKerning error: {traceback.format_exc()}', error=True)


def planGroups(plan, sides):
	"""The groups the plan found, biggest first. -> [dict]

	The plan says it the other way round - each member pointing at the glyph it
	borrows from - because that is what gets written. A person wants to see
	the group, so it is turned inside out here.
	"""
	groups = []
	for side in sides:
		members = {}
		for member, representative in plan[side]['refer'].items():
			members.setdefault(representative, []).append(member)
		for representative, names in members.items():
			# THE REPRESENTATIVE COMES FIRST: it is the one carrying the
			# drawing the rest of them point at.
			groups.append({'side': side, 'name': representative,
					'members': [representative] + sorted(names)})
	groups.sort(key=lambda group: (-len(group['members']), group['name']))
	return groups


def writePlan(font, master, plan, sides, overwrite):
	# -> (drawn, referred, kept). A SIDE THAT ALREADY CARRIES A DRAWING OR A
	# REFERENCE IS LEFT ALONE UNLESS overwrite, WHICH IS WHAT MAKES A SECOND
	# RUN OVER A HALF-DRAWN FONT SAFE.
	drawn = referred = kept = 0
	for side in sides:
		nodesKey, referKey = side.key('Nodes'), side.key('Refer')
		part = plan[side]
		for name, nodes in part['nodes'].items():
			layer = layerFor(font, name, master)
			if layer is None:
				continue
			if not overwrite and (layer.userData[nodesKey] or layer.userData[referKey]):
				kept += 1
				continue
			writeBubble(layer, side, nodes=nodes)
			drawn += 1
		for member, representative in part['refer'].items():
			layer = layerFor(font, member, master)
			if layer is None:
				continue
			if not overwrite and (layer.userData[nodesKey] or layer.userData[referKey]):
				kept += 1
				continue
			if writeBubble(layer, side, refer=representative):
				referred += 1
			else:
				# THE REFERENCE WOULD HAVE CLOSED A CYCLE THROUGH A CHAIN THE
				# RUN DID NOT TOUCH; GIVE THIS ONE ITS OWN BUBBLE INSTEAD.
				fallback = auto.auto_settings(font, master)
				nodes = auto.auto_bubble_nodes(layer, side, gap=fallback['gap'],
					step=fallback['step'], tolerance=fallback['tolerance'],
					max_nodes=fallback['max_nodes'], grid=auto.resolve_grid(font, master),
					slope=fallback['slope'], max_inset=fallback['max_inset'], amplitude=fallback['amplitude'])
				if nodes:
					writeBubble(layer, side, nodes=nodes)
					drawn += 1
	return drawn, referred, kept


def layerFor(font, glyphName, master):
	glyph = font.glyphs[glyphName]
	return glyph.layers[master.id] if glyph is not None else None


def kerningTargets(font, master, text):
	"""The pairs a model string names, with the kerning you gave them.

	-> ([(left, right, value)], [(left, right)] nobody has kerned)

	`nextKerningForLayer_direction_` rather than the kerning table: it
	resolves groups and exceptions exactly as the file does, and hands back
	a 2^63 sentinel for a pair nobody has kerned. Reading the table meant
	knowing that a group key is spelled `@MMK_R_o` in a file and `@o` from
	the API, and that the two do not find each other.
	"""
	layers = preview.previewLayers(font, master, text)
	targets, missing, seen = [], [], set()
	for left, right in zip(layers, layers[1:]):
		pair = (left.parent.name, right.parent.name)
		if pair in seen:
			continue
		seen.add(pair)
		try:
			value = float(left.nextKerningForLayer_direction_(right, 0))
		except Exception:
			continue
		if abs(value) > 100000 or not value:  # never kerned, or kerned to nothing
			missing.append(pair)
			continue
		targets.append((pair[0], pair[1], value))
	return targets, missing


def chosenLayers(font, layers=None):
	"""What a run acts on: what was handed in, or what is selected. -> [layer]"""
	if layers is not None:
		return layers
	return [layer for layer in font.selectedLayers
		if isinstance(layer, GSLayer) and layer.name is not None]


def autoGenerate(font, isLeft, layers=None):
	"""Draw one side of every given layer. -> (drawn, merged, skipped)

	A composite is LEFT TO ITS COMPONENTS where it can be - `mergeFromComponents`
	says so - and only measured where it cannot.
	"""
	master = font.selectedFontMaster
	settings = auto.auto_settings(font, master)
	grid = auto.resolve_grid(font, master)
	side = auto.LEFT if isLeft else auto.RIGHT
	done = skipped = merged = 0
	for layer in chosenLayers(font, layers):
		if mergeFromComponents(layer, side):
			merged += 1
			continue
		nodes = auto.auto_bubble_nodes(
			layer, side,
			gap=settings['gap'], step=settings['step'],
			tolerance=settings['tolerance'], max_nodes=settings['max_nodes'],
			grid=grid, slope=settings['slope'], max_inset=settings['max_inset'],
			amplitude=settings['amplitude'],
		)
		if not nodes:
			skipped += 1
			continue
		writeBubble(layer, side, nodes=nodes)
		done += 1
	log(f'Auto-Generate Bubble ({side}): {done} drawn, {merged} merged, {skipped} skipped')
	return done, merged, skipped


def syncBubble(font, isLeft, layers=None):
	"""One side becomes the live mirror of the other. -> (done, side, other)

	NOTHING IS COPIED: the flag is all that is stored, and `getFinalBubble`
	resolves the shape from the other side every time - including from tempData
	mid-drag, so the synced wall follows the node you are holding.
	"""
	side = of(isLeft)
	other = side.other
	done = 0
	for layer in chosenLayers(font, layers):
		glyph = layer.parent
		glyph.beginUndo()
		try:
			layer.userData[side.key('Mirror')] = True
			# THE THREE WAYS A SIDE CAN GET ITS SHAPE ARE EXCLUSIVE.
			for dead in (other.key('Mirror'), side.key('Refer'), side.key('Nodes')):
				if layer.userData[dead]:
					del layer.userData[dead]
		finally:
			glyph.endUndo()
		done += 1
	return done, side, other
