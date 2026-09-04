# encoding: utf-8
"""The pairs worth looking at while you draw, in the preview panel.

A WALL IS ONLY EVER RIGHT ABOUT A PAIR, and the panel under the edit view is
already the place a designer looks to see a glyph in company. What it shows is
the text you typed, which is the same text for every glyph you go to; what this
shows is the glyph you are ON, standing beside the letters it actually turns up
beside, KERNED BY ITS OWN WALLS. Move a node and the row answers.

WHICH PAIRS: `PKPairs`, off the ranked list the kerner already uses, or the
list somebody typed for that glyph. Which is a different question from drawing
them, and lives in a module with no Glyphs in it.

TAKING THE PANEL is `drawForegroundInPreviewLayer:options:` plus
`needsExtraMainOutlineDrawingInPreviewLayer:` answering False - and then the
panel is showing something nothing on screen accounts for, which is what the
shared `previewbadge` is for: a row of dots in the tab's toolbar naming every
plugin that offers a preview, with the one showing filled in. See that module.
"""

import objc
import traceback

from AppKit import (
	NSAffineTransform,
	NSBezierPath,
	NSColor,
	NSGraphicsContext,
	NSMakeRect,
)
from GlyphsApp import Glyphs
from GlyphsApp.plugins import ReporterPlugin

try:  # the clip is how the panel is found, and how a pass is told from a call
	from Quartz import CGContextGetClipBoundingBox
except Exception:  # pragma: no cover - a Glyphs without Quartz has no panel
	CGContextGetClipBoundingBox = None

import previewbadge
import PKAutoBubble as auto
import PKBubbleStore as store
import PKPairs as pairs
from PKCommonLogic import getFinalBubble, getKernValue, log, namesByCharacter


PLUGIN_ID = 'com.Tosche.PolyKern.pairs'
# Glyphs keeps the ticked reporters here, by class name. Being ticked is the
# whole of this one's state: it draws in the preview panel and nowhere else, so
# "switched on" and "showing the pairs" are one thing, and the View menu and
# the badge's dots are two ways to the same switch.
VISIBLE_REPORTERS = 'visibleReporters'
# A PANEL SHORTER THAN THIS IS SHUT, not open and small: dragged all the way
# down it still reports a point or two.
PREVIEW_MIN_HEIGHT = 16.0

MENU_NAME = 'PolyKern Pairs'


def previewIsOpen(tab):
	"""Is this tab's preview panel open far enough to draw in?"""
	if tab is None:
		return False
	try:
		return float(tab.previewHeight or 0.0) >= PREVIEW_MIN_HEIGHT
	except Exception:
		return False


def previewPanel():
	"""The panel as `(x, y, w, h)` in the coordinates being drawn in. -> tuple

	Taken from the clip, which IS the panel: read in one layer's coordinate
	space or another's it describes the same place on screen, so a row placed
	against it lands identically however many times it is drawn.
	"""
	if CGContextGetClipBoundingBox is None:
		return None
	try:
		context = NSGraphicsContext.currentContext()
		if context is None:
			return None
		try:
			cg = context.CGContext()
		except Exception:
			cg = context.CGContext
		rect = CGContextGetClipBoundingBox(cg)
		x, y = float(rect.origin.x), float(rect.origin.y)
		width, height = float(rect.size.width), float(rect.size.height)
	except Exception:
		return None
	# An empty clip draws nothing, and an infinite one is what CoreGraphics
	# answers when there is no clip at all. Neither is a panel.
	if width <= 0 or height <= 0 or width > 1e7 or height > 1e7:
		return None
	return (x, y, width, height)


def previewGroundView(tab):
	"""The view Glyphs fills the panel's ground with. -> NSView or None

	`GSPreviewBackgroundView`, reached as `previewBackgroundView` on the tab -
	an Objective-C method rather than one of the properties GlyphsApp adds in
	Python, so plain attribute access answers a BOUND METHOD, not a view.
	"""
	found = getattr(tab, 'previewBackgroundView', None)
	if callable(found):
		try:
			found = found()
		except Exception:
			return None
	if found is None or not hasattr(found, 'cacheDisplayInRect_toBitmapImageRep_'):
		return None
	return found


def opensPass(clipX, lastClipX, layerCount=None):
	"""Is this call the first of a preview pass - the one that draws the row?

	Glyphs draws the text left to right and hands each layer its own
	coordinates, so the panel's left edge, read off the clip, sits further and
	further behind the origin as the pass goes on. A value that has NOT gone
	down is therefore the start of the next pass.

	`layerCount` is how many glyphs the text has, and one of them settles it
	outright: a pass over a single glyph is a single call, so every call opens
	one. That case has to be answered before the clip is consulted, because it
	is the case the clip cannot answer - with nothing else in the text the only
	thing moving the panel's edge is the drag itself.
	"""
	if layerCount is not None and layerCount <= 1:
		return True
	if lastClipX is None:
		return True
	return clipX > lastClipX - 0.001


class PolyKernPairs(ReporterPlugin):

	# -------------------------------------------------------------- lifecycle

	@objc.python_method
	def settings(self):
		# Glyphs puts this in the View menu, as "Show PolyKern Pairs", and
		# remembers whether it is ticked.
		self.menuName = Glyphs.localize({'en': MENU_NAME})
		self._lastClipX = None
		self._ground = None
		self._groundKey = None
		self._table = None
		self._tableStamp = None

	@objc.python_method
	def start(self):
		try:
			previewbadge.register(
				identifier=PLUGIN_ID,
				name=Glyphs.localize({'en': MENU_NAME}),
				isActive=self.showing,
				activate=lambda: self.setShowing(True),
				deactivate=lambda: self.setShowing(False),
			)
		except Exception:
			log(f'PolyKernPairs start error: {traceback.format_exc()}', error=True)

	# ------------------------------------------------------------------ state

	@objc.python_method
	def showing(self):
		"""Is the reporter ticked in the View menu?"""
		try:
			visible = Glyphs.defaults[VISIBLE_REPORTERS] or ()
			return str(self.className()) in [str(name) for name in visible]
		except Exception:
			return False

	@objc.python_method
	def setShowing(self, wanted):
		"""Tick or untick it from somewhere that is not the menu.

		THE SAME SWITCH THE MENU FLIPS, because there is only one: the badge's
		dot and the menu item cannot drift apart if they are writing the same
		default. Glyphs watches that list, so writing it is what turns the
		drawing on.
		"""
		try:
			name = str(self.className())
			visible = [str(one) for one in (Glyphs.defaults[VISIBLE_REPORTERS] or ())]
			if wanted and name not in visible:
				visible.append(name)
			elif not wanted and name in visible:
				visible.remove(name)
			else:
				return
			Glyphs.defaults[VISIBLE_REPORTERS] = visible
			previewbadge.refresh()
			Glyphs.redraw()
		except Exception:
			log(f'PolyKernPairs setShowing error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def drawingInPreview(self):
		"""Is the row going into the panel now?

		Ticked says it belongs there; the panel has to be open for it to go.
		Shut, Glyphs draws its own preview as usual - the tick is a preference
		for the panel, not an instruction to empty it.
		"""
		if not self.showing():
			return False
		font = Glyphs.font
		return previewIsOpen(font.currentTab if font is not None else None)

	@objc.python_method
	def currentLayer(self):
		"""The layer being edited. -> (font, layer)"""
		font = Glyphs.font
		if font is None:
			return None, None
		layer = None
		tab = font.currentTab
		if tab is not None:
			try:
				layer = tab.activeLayer()
			except Exception:
				layer = None
		if layer is None:
			layers = font.selectedLayers
			layer = layers[0] if layers else None
		if layer is None or layer.parent is None:
			return font, None
		return font, layer

	@objc.python_method
	def textLength(self):
		"""How many glyphs the tab's text has, or None. -> int

		The panel draws one of them per call, so this is the length of a pass -
		and a pass of one is what tells the row to stop reading the clip.
		"""
		try:
			tab = Glyphs.font.currentTab
			return len(tab.layers) if tab is not None else None
		except Exception:
			return None

	@objc.python_method
	def namesTable(self, font):
		"""Which glyph draws each character. -> {str: str}

		Kept between draws and rebuilt when the font's glyph count changes,
		which is the cheap half of "is this still the same font": reading every
		glyph's unicodes on every frame of a drag is not what the panel is for.
		"""
		stamp = (id(font), len(font.glyphs))
		if self._table is None or stamp != self._tableStamp:
			self._table = namesByCharacter(font)
			self._tableStamp = stamp
		return self._table

	# ---------------------------------------------------------------- the row

	@objc.python_method
	def layerFor(self, font, name, masterId):
		glyph = font.glyphs[name]
		if glyph is None:
			return None
		return glyph.layers[masterId]

	@objc.python_method
	def kernBetween(self, font, leftLayer, rightLayer):
		"""What PolyKern would put between these two. -> float

		THE WALLS, WHICH IS THE POINT: the row is here to show what the wall
		being drawn does to the pairs it has to answer for, and the font's own
		kerning is what it says INSTEAD of that. Where a wall cannot be
		resolved the font's value stands in, so a pair is never drawn crashing
		just because one of the two has no bubble yet.
		"""
		try:
			wallR = getFinalBubble(leftLayer, isLeft=False)
			wallL = getFinalBubble(rightLayer, isLeft=True)
			if wallR is not None and wallL is not None:
				master = leftLayer.associatedFontMaster()
				value, row = getKernValue(wallR, wallL, int(leftLayer.width),
					withRow=True, space=auto.fit_space(font, master))
				if row is not None and value != float('inf'):
					return -float(value)
			existing = store.effectiveKerning(leftLayer, rightLayer, font,
				leftLayer.associatedMasterId)
			return float(existing or 0.0)
		except Exception:
			log(f'PolyKernPairs kernBetween error: {traceback.format_exc()}', error=True)
			return 0.0

	@objc.python_method
	def rowCells(self):
		"""The whole row as things to draw. -> ([(layer, advance)], total)

		An advance is what to move on by AFTER that glyph: its own width plus
		the kern to the one beside it, and after the second of a pair the gap
		to the next pair. Both are in font units; the scaling is done once,
		against the panel, in `PKPairs.placeRun`.
		"""
		font, layer = self.currentLayer()
		if layer is None:
			return ([], 0.0)
		glyph = layer.parent
		masterId = layer.associatedMasterId
		table = self.namesTable(font)
		gap = font.upm * pairs.PAIR_GAP_EM
		cells, total = [], 0.0
		shown = pairs.pairsFor(glyph, glyph.name, table)
		for leftName, rightName in shown:
			left = self.layerFor(font, leftName, masterId)
			right = self.layerFor(font, rightName, masterId)
			if left is None or right is None:
				continue
			kern = self.kernBetween(font, left, right)
			advance = float(left.width) + kern
			cells.append((left, advance))
			cells.append((right, float(right.width) + gap))
			total += advance + float(right.width) + gap
		if cells:
			# THE LAST GAP IS NOT PART OF THE ROW. Counted in, the row is
			# centred a gap to the left of where it looks like it should be.
			total -= gap
		return (cells, total)

	@objc.python_method
	def groundKey(self):
		try:
			black = bool(Glyphs.defaults['GSPreview_Black'])
		except Exception:
			black = None
		try:
			from AppKit import NSApp
			appearance = str(NSApp().effectiveAppearance().name())
		except Exception:
			appearance = None
		return (black, appearance)

	@objc.python_method
	def sampleGround(self):
		"""Take the panel's ground colour off the panel itself. -> NSColor

		By having `GSPreviewBackgroundView` draw one pixel of itself, rather
		than working it out from the preview's Black setting: the panel is not
		black when that is on, it is a very dark grey of Glyphs' own, and a
		panel repainted in a nearly-right grey is worse than what the
		repainting was for.
		"""
		key = self.groundKey()
		if self._ground is not None and key == self._groundKey:
			return self._ground
		self._groundKey = key
		self._ground = None
		try:
			tab = Glyphs.font.currentTab if Glyphs.font is not None else None
			view = previewGroundView(tab) if tab is not None else None
			if view is None:
				return None
			spot = NSMakeRect(0.0, 0.0, 1.0, 1.0)
			rep = view.bitmapImageRepForCachingDisplayInRect_(spot)
			if rep is None:
				return None
			view.cacheDisplayInRect_toBitmapImageRep_(spot, rep)
			self._ground = rep.colorAtX_y_(0, 0)
		except Exception:
			self._ground = None
		return self._ground

	@objc.python_method
	def clearPanel(self, panel):
		"""Paint the panel back to its own ground before the row goes in.

		Glyphs is told not to draw the panel's glyphs while the row has it, and
		that flag covers the ACTIVE layer only: the rest of the text still
		ghosts through at a few per cent, by a path of its own. Reporters draw
		last, so painting the ground back in covers whatever drew it.
		"""
		ground = self.sampleGround()
		if ground is None or panel is None:
			return False
		context = NSGraphicsContext.currentContext()
		context.saveGraphicsState()
		ground.set()
		NSBezierPath.fillRect_(NSMakeRect(*panel))
		context.restoreGraphicsState()
		return True

	# ------------------------------------------------------------- the drawing

	def drawForegroundInPreviewLayer_options_(self, layer, options):
		"""Draw the row in the panel, in place of what it would show.

		Glyphs calls this once per layer of the tab's text, each in that
		layer's own coordinate space, so the row is drawn on the FIRST of them
		and skipped on the rest - which call that is comes from `opensPass`.

		The row is placed against the panel rather than the text origin: it is
		not the tab's text, it has nothing to do with where that text sits, and
		the panel is the same place on screen whichever layer's coordinates it
		is read in.
		"""
		try:
			if not self.drawingInPreview():
				return
			panel = previewPanel()
			if panel is not None:
				if not opensPass(panel[0], self._lastClipX, self.textLength()):
					self._lastClipX = panel[0]
					return
				self._lastClipX = panel[0]
			# FIRST IN THE PASS, WHETHER OR NOT THERE IS A ROW: an empty panel
			# is the honest answer for a glyph with no pairs, and a ghost of
			# the text somebody did not ask for is not.
			self.clearPanel(panel)
			if panel is None:
				return
			cells, total = self.rowCells()
			if not cells:
				return
			font, edited = self.currentLayer()
			master = edited.associatedFontMaster()
			placed = pairs.placeRun(panel, total, master.ascender, master.descender)
			if placed is None:
				return
			scale, left, baseline = placed
			cursor = 0.0
			for cell, advance in cells:
				self.drawGlyph(cell, left + cursor * scale, baseline, scale)
				cursor += advance
		except Exception:
			log(f'PolyKernPairs draw error: {traceback.format_exc()}', error=True)

	@objc.typedSelector(b'Z@:@')
	def needsExtraMainOutlineDrawingInPreviewLayer_(self, layer):
		"""Stop Glyphs drawing the panel's own glyphs while the row has it.

		This one is the preview's alone. Its neighbour,
		`needsExtraMainOutlineDrawingForInactiveLayer_`, covers the preview AND
		the inactive glyphs in the edit view, so answering there would take the
		tab's text out of the edit view too.
		"""
		return not self.drawingInPreview()

	@objc.python_method
	def drawGlyph(self, layer, x, baseline, scale):
		"""One glyph of the row, at the panel's own scale.

		THE TRANSFORM GOES ON THE CONTEXT, not on the path: `completeBezierPath`
		is the layer's own, and transforming it in place would move the glyph
		everywhere else it is drawn.
		"""
		try:
			path = layer.completeBezierPath
			if path is None or path.isEmpty():
				return
			context = NSGraphicsContext.currentContext()
			context.saveGraphicsState()
			transform = NSAffineTransform.transform()
			transform.translateXBy_yBy_(x, baseline)
			transform.scaleBy_(scale)
			transform.concat()
			NSColor.textColor().set()
			path.fill()
			context.restoreGraphicsState()
		except Exception:
			log(f'PolyKernPairs drawGlyph error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
