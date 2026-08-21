# encoding: utf-8
"""The grid of glyphs that Set Refer Glyphs Automatically found.

A count of how many sides were grouped says nothing about whether the grouping
was any good. The glyphs side by side, each with its measured wall drawn on the
side it was grouped on, say it at a glance - which is what AZ Fingerprints'
Groups tab is for, and why this borrows its shape.

Its own module because it is a view: it knows about groups, a font and a master
id, and nothing at all about the tool that puts it on a sheet.
"""

import traceback

import objc

from Cocoa import (
	NSAffineTransform,
	NSAttributedString,
	NSBezierPath,
	NSColor,
	NSFont,
	NSFontAttributeName,
	NSForegroundColorAttributeName,
	NSMakeRect,
	NSPoint,
	NSView,
)

from BKCommonLogic import getFinalBubble, log




# --- THE GROUPS AUTO-GROUP FONT FOUND --------------------------------------

# One cell per glyph, in bands of one group each. DRAWN RATHER THAN BUILT OUT
# OF CONTROLS, the way AZ Fingerprints draws its groups: a GlyphView per glyph
# would be one NSView per cell, and none of them could show WHICH side the
# group was made on - the only thing this view has to say that a tab of the
# same glyphs does not.
GROUP_CELL = 74.0
GROUP_CAPTION = 14.0
GROUP_GUTTER = 8.0
GROUP_PAD = 12.0
GROUP_HEADER = 22.0
GROUP_INSET = 6.0


def closedWall(wall, isLeft):
	"""The pocket between a wall and the far edge of its own extent. -> path

	The wall is an open line, and an open line says which shape was measured
	only to someone already reading it closely. Closed against its own extreme
	it becomes the piece of whitespace the group agrees about, which is the
	thing being grouped.
	"""
	try:
		count = wall.elementCount()
		if count < 2:
			return None
		first = wall.elementAtIndex_associatedPoints_(0)[1][0]
		last = wall.elementAtIndex_associatedPoints_(count - 1)[1][0]
		bounds = wall.bounds()
		edge = bounds.origin.x if isLeft else bounds.origin.x + bounds.size.width
		pocket = NSBezierPath.alloc().init()
		pocket.appendBezierPath_(wall)
		pocket.lineToPoint_(NSPoint(edge, last.y))
		pocket.lineToPoint_(NSPoint(edge, first.y))
		pocket.closePath()
		return pocket
	except Exception:
		return None


class BKGroupGridView(NSView):
	"""Every glyph put in a group, with the side it was grouped on drawn.

	Prefixed because an ObjC class name is process-global and Glyphs loads
	every plugin into one runtime.

	Carries `_groups`, `_font` and `_masterId`, assigned by the sheet.
	"""

	def isFlipped(self):  # AppKit selector name
		# Bands fill from the top, which is where a scrolled list starts.
		return True

	@objc.python_method
	def setGroups(self, groups, font, masterId):
		self._groups = groups
		self._font = font
		self._masterId = masterId
		self._art = {}
		self.relayout()

	@objc.python_method
	def relayout(self, width=None):
		"""Where every band and cell goes, and how tall that makes this. -> None

		The only place the geometry is decided, so the draw has nothing to work
		out for itself. Sets the frame through super, because this view's own
		`setFrameSize_` calls back in here.
		"""
		try:
			if width is None:
				width = float(self.frame().size.width)
			columns = max(1, int((width - 2 * GROUP_PAD + GROUP_GUTTER)
					// (GROUP_CELL + GROUP_GUTTER)))
			row = GROUP_CELL + GROUP_CAPTION + GROUP_GUTTER
			self._bands, self._cells = [], []
			top = GROUP_PAD
			for group in getattr(self, '_groups', ()):
				self._bands.append((top, group))
				top += GROUP_HEADER
				members = group['members']
				for index, name in enumerate(members):
					self._cells.append((
						GROUP_PAD + (index % columns) * (GROUP_CELL + GROUP_GUTTER),
						top + (index // columns) * row,
						name, group['side']))
				top += ((len(members) + columns - 1) // columns) * row + GROUP_PAD
			objc.super(BKGroupGridView, self).setFrameSize_((width, max(top, 1.0)))
		except Exception:
			log(f'BKGroupGridView relayout error: {traceback.format_exc()}', error=True)

	def setFrameSize_(self, size):
		# A SCROLL VIEW RESIZES ITS DOCUMENT VIEW AND TELLS IT NOTHING ELSE, so
		# this is the only place a width change is heard. The flag is because
		# relayout sets the height, and without it that would come straight back
		# through here.
		if getattr(self, '_laying', False):
			objc.super(BKGroupGridView, self).setFrameSize_(size)
			return
		self._laying = True
		try:
			objc.super(BKGroupGridView, self).setFrameSize_(size)
			self.relayout(float(size.width))
		finally:
			self._laying = False

	def drawRect_(self, rect):
		try:
			appearance = self.effectiveAppearance()
			if hasattr(appearance, 'performAsCurrentDrawingAppearance_'):
				appearance.performAsCurrentDrawingAppearance_(self.paint)
			else:
				self.paint()
		except Exception:
			log(f'BKGroupGridView error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def paint(self):
		try:
			NSColor.textBackgroundColor().set()
			NSBezierPath.fillRect_(self.bounds())
			heading = {
				NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
				NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
			}
			for top, group in getattr(self, '_bands', ()):
				side = 'left' if group['side'].isLeft else 'right'
				count = len(group['members'])
				NSAttributedString.alloc().initWithString_attributes_(
					f"{group['name']} — {side} · {count} glyphs", heading
				).drawAtPoint_(NSPoint(GROUP_PAD, top + 3.0))
			caption = {
				NSFontAttributeName: NSFont.systemFontOfSize_(10.0),
				NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
			}
			for left, top, name, side in getattr(self, '_cells', ()):
				self.paintCell(left, top, name, side, caption)
		except Exception:
			log(f'BKGroupGridView paint error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def art(self, layer, name):
		# COMPLETE, i.e. what the glyph looks like rather than what it is made
		# of: components in, overlaps already unioned. Cached because a band of
		# thirty cells is thirty of these on every draw otherwise.
		cache = getattr(self, '_art', None)
		if cache is None:
			cache = self._art = {}
		if name not in cache:
			try:
				cache[name] = layer.completeBezierPath
			except Exception:
				cache[name] = None
		return cache[name]

	@objc.python_method
	def paintCell(self, left, top, name, side, caption):
		try:
			glyph = self._font.glyphs[name]
			if glyph is None:
				return
			layer = glyph.layers[self._masterId]
			if layer is None:
				return
			master = layer.associatedFontMaster()
			NSColor.textColor().colorWithAlphaComponent_(0.05).set()
			NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
				NSMakeRect(left, top, GROUP_CELL, GROUP_CELL), 5.0, 5.0).fill()
			# ONE SCALE FOR EVERY CELL, from the master's own ascender to its
			# descender: cells fitted to their own ink would draw an `o` and an
			# `H` the same height and say the group was about something it is not.
			span = float(master.ascender - master.descender) or float(self._font.upm)
			scale = (GROUP_CELL - 2 * GROUP_INSET) / span
			transform = NSAffineTransform.transform()
			transform.translateXBy_yBy_(
				left + (GROUP_CELL - float(layer.width) * scale) / 2.0,
				top + GROUP_INSET + master.ascender * scale)
			# NEGATIVE Y: this view is flipped and the glyph is not.
			transform.scaleXBy_yBy_(scale, -scale)
			outline = self.art(layer, name)
			if outline is not None:
				drawn = outline.copy()
				drawn.transformUsingAffineTransform_(transform)
				NSColor.textColor().colorWithAlphaComponent_(0.7).set()
				drawn.fill()
			wall = getFinalBubble(layer, side.isLeft)
			if wall is not None:
				color = side.color()
				pocket = closedWall(wall, side.isLeft)
				if pocket is not None:
					pocket.transformUsingAffineTransform_(transform)
					color.colorWithAlphaComponent_(0.25).set()
					pocket.fill()
				edge = wall.copy()
				edge.transformUsingAffineTransform_(transform)
				color.set()
				edge.setLineWidth_(1.2)
				edge.stroke()
			label = NSAttributedString.alloc().initWithString_attributes_(name, caption)
			label.drawAtPoint_(NSPoint(
				left + (GROUP_CELL - label.size().width) / 2.0,
				top + GROUP_CELL + 1.0))
		except Exception:
			log(f'BKGroupGridView cell error: {traceback.format_exc()}', error=True)
