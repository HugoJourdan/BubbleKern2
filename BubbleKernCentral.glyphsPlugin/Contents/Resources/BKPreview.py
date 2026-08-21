# encoding: utf-8
"""The settings window's preview: a line of text, spaced by the walls.

Which is the question the settings panel cannot otherwise answer - every
slider in it moves a wall, and a wall only matters for what it does to a pair.

NOTHING HERE KNOWS ABOUT THE TOOL. The walls are generated from the settings
rather than read from userData, so drawing the preview touches no file; the
only state is the preferences, read at draw time.
"""

import math
import traceback

from GlyphsApp import Glyphs, GSControlLayer

from Cocoa import (
	NSAffineTransform,
	NSAppearance,
	NSAttributedString,
	NSBezierPath,
	NSColor,
	NSFont,
	NSFontAttributeName,
	NSForegroundColorAttributeName,
	NSGraphicsContext,
	NSMakeRect,
	NSPoint,
	NSView,
)

import BKAutoBubble as auto
from BKCommonLogic import getKernValue, log
from BKSide import SIDES


PREVIEW_TEXT = 'AVoTnoun'  # a diagonal, a flat pair and a round one


# THE PREVIEW'S TEXT SIZE, as a percentage of the size that fits the box. 100
# is the whole string end to end, and it is also the TOP of the range: the
# slider only shrinks. Bigger than fits means a preview with its ends cut off,
# and the ends of a string are where the pairs someone typed it for usually are.
PREVIEW_SIZE_RANGE = (40.0, 100.0)
# WHAT THE CONTROLS ON THE PREVIEW TAKE UP, top and bottom, so the drawing can
# keep out from under them. Measured from the view's own edges: it draws
# unflipped, the switches sit along the foot and the size slider along the top.
PREVIEW_TOP_ROOM = 26.0
PREVIEW_FOOT_ROOM = 28.0
# WHERE THE KERN FIGURES STAND. `LIFT` clears the descender, `DROP` is the
# ten points past it they were asked to sit at, and `ROOM` is what has to be
# kept free under the line for the two of them: 26 is the least that works,
# and the least is what leaves the type the most.
KERN_LABEL_LIFT = 14.0
KERN_LABEL_DROP = 10.0
KERN_LABEL_ROOM = 26.0


def previewEmBottom(usableHeight, lineHeight):
	"""Where the line's descender sits in the preview box. -> y

	THE FIGURES' ROOM GOES UNDER THE LINE, so it is ADDED here, not subtracted.
	See CLAUDE.md.
	"""
	return PREVIEW_FOOT_ROOM + (usableHeight - lineHeight + KERN_LABEL_ROOM) / 2.0


def kernLabelY(emBottom):
	"""Where a kern figure's line box starts, under a line footed at `emBottom`.

	NOT BELOW THE CLIP: kept as a floor, though with the room reserved under
	the line it is not reached - a glyph deeper than the descender it was
	measured from could still find it.
	"""
	return max(PREVIEW_FOOT_ROOM + 2.0,
		emBottom - KERN_LABEL_LIFT - KERN_LABEL_DROP)
# How near a neighbour's line a dragged node has to come, in SCREEN points,


def previewLayers(font, master, text):
	"""The layers a typed string names, in order. -> [layer]

	Anything the font has no glyph for is dropped rather than shown as a
	blank: the preview is about the pairs it CAN show.
	"""
	layers = []
	for character in text:
		glyph = font.glyphs[character]
		if glyph is None:  # a digit or an accent arrives as a character, not a name
			try:
				info = Glyphs.glyphInfoForUnicode('%04X' % ord(character))
				glyph = font.glyphs[info.name] if info is not None else None
			except Exception:
				glyph = None
		if glyph is None:
			continue
		layer = glyph.layers[master.id]
		if layer is not None:
			layers.append(layer)
	return layers


def currentTabLayers(font, master):
	"""The layers the tab in front is showing. -> [layer] or None

	TAKEN AS LAYERS, NOT AS ITS TEXT. A tab's string spells a glyph with no
	unicode as `/name`, which read a character at a time is nine wrong glyphs
	rather than one right one - and the layers are already the answer that
	string was going to be turned back into.
	"""
	try:
		tab = font.currentTab
		if tab is None:
			return None
		layers = []
		# tab.layers HAS NO __len__ - IT RAISES - SO WALK IT INSTEAD.
		for layer in tab.layers:
			if isinstance(layer, GSControlLayer):  # a line break is not a glyph
				continue
			glyph = layer.parent
			if glyph is None:
				continue
			own = glyph.layers[master.id]
			if own is not None:
				layers.append(own)
		return layers or None
	except Exception:
		log(f'currentTabLayers error: {traceback.format_exc()}', error=True)
		return None


def previewWalls(layer, settings, grid):
	"""Both walls the current settings would generate. -> (left, right) or None

	Absolute paths, so `getKernValue` can read them straight off - the right
	side is stored relative to the advance and is put back here.
	"""
	paths = []
	for side in SIDES:
		nodes = auto.auto_bubble_nodes(
			layer, side, gap=settings['gap'], step=settings['step'],
			tolerance=settings['tolerance'], max_nodes=settings['max_nodes'],
			grid=grid, slope=settings['slope'], max_inset=settings['max_inset'],
			amplitude=settings['amplitude'])
		if not nodes:
			return None  # no ink to measure: `space` and its like
		path = NSBezierPath.alloc().init()
		for index, (x, y) in enumerate(nodes):
			point = NSPoint(x if side.isLeft else layer.width + x, y)
			if index == 0:
				path.moveToPoint_(point)
			else:
				path.lineToPoint_(point)
		paths.append(path)
	return paths[0], paths[1]


def labelString(text, size, color):
	attributes = {
		NSFontAttributeName: NSFont.systemFontOfSize_(size),
		NSForegroundColorAttributeName: color,
	}
	return NSAttributedString.alloc().initWithString_attributes_(text, attributes)


def previewLabel(text, x, y, size, color, centred=False):
	string = labelString(text, size, color)
	if centred:
		x -= string.size().width / 2.0
	string.drawAtPoint_(NSPoint(x, y))
	return string.size().width


def previewLine(font, master, text, settings, grid, layers=None):
	"""One line of the preview, measured. -> dict or None

	The walls are generated rather than read from userData, so the preview
	shows what a run WOULD write and touches nothing.
	"""
	if layers is None:
		layers = previewLayers(font, master, text)
	if not layers:
		return None
	walls = [previewWalls(layer, settings, grid) for layer in layers]
	kerns = []
	for index in range(len(layers) - 1):
		left, right = walls[index], walls[index + 1]
		value = 0.0
		if left is not None and right is not None:
			raw = getKernValue(left[1], right[0], int(layers[index].width),
				space=auto.fit_space(font, master))
			if raw is not None and not math.isinf(float(raw)):
				value = float(raw)
		kerns.append(value)
	return {'layers': layers, 'walls': walls, 'kerns': kerns}


def previewPositions(line, kerned):
	"""Where each glyph of a line starts, and how wide the line is."""
	positions, pen = [], 0.0
	for index, layer in enumerate(line['layers']):
		positions.append(pen)
		# What the kerner writes is the NEGATIVE of what the walls measure.
		pen += layer.width - (line['kerns'][index] if kerned and index < len(line['kerns']) else 0.0)
	return positions, pen


def drawPreview(bounds):
	"""The typed string, spaced by the kerning the current settings generate.

	Which is the question the settings window cannot otherwise answer: every
	slider in it moves a wall, and a wall only matters for what it does to a
	pair.
	"""
	NSColor.textBackgroundColor().set()
	NSBezierPath.fillRect_(bounds)
	font = Glyphs.font
	master = font.selectedFontMaster if font is not None else None
	faint = NSColor.secondaryLabelColor()
	if font is None or master is None:
		previewLabel('Open a font to preview', 12, bounds.size.height / 2 - 7, 11, faint)
		return
	# NOTHING TYPED MEANS THE TAB IN FRONT. The window is for watching a
	# setting move a pair, and the pair being looked at is nearly always the
	# one already open behind it.
	text = auto._pref(auto.PREF_PREVIEW_TEXT, None)
	layers = None
	if not text:
		layers = currentTabLayers(font, master)
		if layers is None:
			text = PREVIEW_TEXT
	settings = auto.auto_settings(font, master)
	grid = auto.resolve_grid(font, master)
	# The walls are always BUILT: they are what decides the spacing. The
	# switches only say what to draw of it.
	showWalls = bool(auto._pref(auto.PREF_PREVIEW_WALLS, True))
	kerned = bool(auto._pref(auto.PREF_PREVIEW_KERNED, True))

	line = previewLine(font, master, text, settings, grid, layers)
	# SCALED UNKERNED, ALWAYS. Toggling Preview Kerning must not resize the
	# text: the switch is there to show what the kerning did, and nothing
	# about it can be seen if the whole line changes size with it. So the
	# SCALE comes from the unkerned line and turning kerning on tightens the
	# glyphs inside a box that stays the size it was.
	plain = 0.0
	if line is not None:
		plain = previewPositions(line, False)[1]
		line['positions'], line['width'] = previewPositions(line, kerned)
	if line is None or plain <= 0:
		previewLabel('No glyphs in this font for that text', 12,
					bounds.size.height / 2 - 7, 11, faint)
		return

	top, bottom = float(master.ascender), float(master.descender)
	padding = 12.0
	# THE CONTROLS SIT ON THIS VIEW, so the drawing keeps out of their way:
	# the size slider along the top, the switches along the foot.
	usableWidth = bounds.size.width - 2 * padding
	usableHeight = bounds.size.height - PREVIEW_TOP_ROOM - PREVIEW_FOOT_ROOM
	if usableWidth <= 0 or usableHeight <= 0 or top <= bottom:
		return
	# AS BIG AS IT GOES, times whatever the slider says - and the slider tops
	# out at 100, so this only ever comes down from the fitting size.
	size = auto._amount(auto._pref(auto.PREF_PREVIEW_SIZE, None), 100.0,
						PREVIEW_SIZE_RANGE) / 100.0
	# RESERVED WHETHER OR NOT ANYTHING IS WRITTEN IN IT. This room feeds both
	# the scale and the vertical centring, so letting it change with the switch
	# resized the text and moved it down the box - the last of the jumping.
	# Kerning on or off, the line sits in exactly the same place.
	scale = min(usableWidth / plain,
				(usableHeight - KERN_LABEL_ROOM) / (top - bottom)) * size
	if scale <= 0:
		return
	# CENTRED ON WHAT IS ACTUALLY DRAWN, though. The kerned line is the
	# shorter of the two, and centring it on the unkerned width left it
	# hanging off to one side with the difference banked up on the other.
	drawn = line['width'] if line['width'] > 0 else plain
	originX = padding + (usableWidth - drawn * scale) / 2.0
	emBottom = previewEmBottom(usableHeight, (top - bottom) * scale)
	# CLIPPED ALL THE SAME. The line fits, but a glyph is not obliged to stay
	# inside the ascender and descender the box was measured from, and one that
	# does not would draw over the switches at the foot.
	NSGraphicsContext.currentContext().saveGraphicsState()
	NSBezierPath.clipRect_(NSMakeRect(0, PREVIEW_FOOT_ROOM, bounds.size.width,
									usableHeight))
	try:
		drawPreviewLine(line, originX, emBottom - bottom * scale, scale,
						top, bottom, showWalls, kerned, faint)
	finally:
		NSGraphicsContext.currentContext().restoreGraphicsState()


def drawPreviewLine(line, originX, originY, scale, top, bottom,
					showWalls, kerned, faint):
	positions, kerns = line['positions'], line['kerns']
	baseline = NSBezierPath.bezierPath()
	baseline.moveToPoint_(NSPoint(originX, originY))
	baseline.lineToPoint_(NSPoint(originX + line['width'] * scale, originY))
	NSColor.separatorColor().set()
	baseline.setLineWidth_(1.0)
	baseline.stroke()

	for index, layer in enumerate(line['layers']):
		transform = NSAffineTransform.transform()
		transform.translateXBy_yBy_(originX + positions[index] * scale, originY)
		transform.scaleBy_(scale)
		outline = layer.completeBezierPath
		if outline is not None:
			shape = outline.copy()
			shape.transformUsingAffineTransform_(transform)
			NSColor.textColor().colorWithAlphaComponent_(0.85).set()
			shape.fill()
		pair = line['walls'][index]
		if pair is None or not showWalls:
			continue
		for side, wall in zip(SIDES, pair):
			drawn = wall.copy()
			drawn.transformUsingAffineTransform_(transform)
			side.color().colorWithAlphaComponent_(0.85).set()
			drawn.setLineWidth_(1.0)
			drawn.stroke()

	if not kerned:
		return
	# WHAT THE KERN TOOK OUT, over the type rather than beside it: the strip
	# between where the next glyph now starts and where it would have.
	#
	# ONLY WITH THE BUBBLES HIDDEN. The band and the two walls it lies between
	# are the same fact drawn twice, and drawn together the band is a magenta
	# wash over the one seam a person is trying to look at.
	if not showWalls:
		NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.0, 1.0, 0.2).set()
		for index, value in enumerate(kerns):
			if -value >= 0:  # only a tightening removes anything
				continue
			NSBezierPath.fillRect_(NSMakeRect(
				originX + positions[index + 1] * scale, originY + bottom * scale,
				abs(value) * scale, (top - bottom) * scale))

	labelY = kernLabelY(originY + bottom * scale)
	lastRight = None
	for index, value in enumerate(kerns):
		applied = -int(round(value))
		if applied == 0:
			continue
		seam = originX + positions[index + 1] * scale
		# UNDER THE MIDDLE OF THE BAND, NOT UNDER ITS EDGE. The seam is where
		# the band starts, so a figure centred on it hung half outside the
		# strip it belongs to and read as the neighbour's. The band runs from
		# the seam by whatever the kern moved, either way: a tightening takes
		# it to the right of the seam and a loosening to the left, which is
		# the one expression below.
		centre = seam + value * scale / 2.0
		# A NUMBER THAT WOULD LAND ON THE ONE BEFORE IT is dropped rather than
		# drawn: two overlapping labels read as one wrong number, and the band
		# over the type already says which seams were kerned.
		width = labelString(str(applied), 9, faint).size().width
		if lastRight is not None and centre - width / 2.0 < lastRight + 3.0:
			continue
		previewLabel(str(applied), centre, labelY, 9, faint, centred=True)
		lastRight = centre + width / 2.0


class BubbleKernPreviewView(NSView):

	def drawRect_(self, rect):
		# Under THIS VIEW'S appearance, not the app's: a semantic colour asked
		# for outside a drawing appearance resolves against the APPLICATION,
		# which is how a reporter ends up drawing white on white in Glyphs.
		try:
			appearance = self.effectiveAppearance()
			try:
				appearance.performAsCurrentDrawingAppearance_(lambda: drawPreview(self.bounds()))
			except AttributeError:  # before macOS 11
				previous = NSAppearance.currentAppearance()
				NSAppearance.setCurrentAppearance_(appearance)
				try:
					drawPreview(self.bounds())
				finally:
					NSAppearance.setCurrentAppearance_(previous)
		except Exception:
			log(f'drawPreview error: {traceback.format_exc()}', error=True)
