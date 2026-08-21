# encoding: utf-8
"""The slabs this tool's section is drawn on, beside Glyphs' own info box.

`InspectorGroup` is shaped like the box Glyphs shows a node's X and Y in - its
own class, so the corner, the colour and the way it answers the theme are the
app's rather than an imitation that drifts the first time either changes.

`PillView` is the panel each side's controls sit on: two slabs, each striped in
the colour the canvas draws that wall in and pointed out at the sidebearing its
controls edit. See CLAUDE.md.
"""

import traceback

import objc
import vanilla

from Cocoa import (
	NSBezierPath,
	NSColor,
	NSImage,
	NSImageOnly,
	NSPoint,
	NSView,
)

from BKCommonLogic import log



# UI STUFF FOR DISPLAYING INFO BOX
# Patched Vanilla Group class to generate Info Box
GSInspectorView = objc.lookUpClass("GSInspectorView")


class InspectorGroup(vanilla.Group):
	"""A slab shaped like the one Glyphs shows a node's X and Y in.

	Its own class, so the corner, the colour and the way it answers the theme
	are the app's rather than an imitation that drifts the first time either
	changes. Falls back to a plain view where the class is not there to be
	found, which is only ever outside the app.
	"""
	nsViewClass = (GSInspectorView
		if isinstance(GSInspectorView, type) and issubclass(GSInspectorView, NSView)
		else NSView)


# THE PANEL EACH SIDE'S CONTROLS SIT IN. The grey is the window background,
# resolved against this view's own appearance rather than picked by hand: the
# info box beside it is that colour, and a grey chosen to look like it only
# looked like it until one of them changed.
PILL_RADIUS = 8.0
# How far the point sticks out of the slab, and how much room the outer
# margin therefore has to leave for it.
PILL_POINT = 10.0
# THE MENU BUTTONS' GEAR. Filled: at 13pt the outlined one is a ring of hairlines
# that greys out into the bezel behind it, and both menus wear the same one.
GEAR_SYMBOL = 'gearshape.fill'
# The tip is blunted rather than sharp. The angle it comes to is acute
# enough that a small radius reads as a lot of rounding, which is why this
# is well under the slab's own.
PILL_TIP = 3.0


def roundedPath(corners, radii):
	"""A closed polygon with its own radius at each corner. -> NSBezierPath

	`arcFromPoint:toPoint:radius:` rounds the corner at its FIRST point and a
	radius of zero leaves it mitred, so one call per corner draws both kinds.
	The path starts halfway along an edge rather than on a corner, because
	closePath draws a straight line back to where it began and starting on a
	corner would put the mitre back on the last one rounded.
	"""
	count = len(corners)
	path = NSBezierPath.alloc().init()
	path.moveToPoint_(NSPoint(
		(corners[0].x + corners[1].x) / 2.0,
		(corners[0].y + corners[1].y) / 2.0))
	for index in range(count):
		corner = (index + 1) % count
		path.appendBezierPathWithArcFromPoint_toPoint_radius_(
			corners[corner], corners[(index + 2) % count], radii[corner])
	path.closePath()
	return path


class PillView(NSView):
	"""A rounded slab with a point on its outer edge, in the side's colour.

	Two identical boxes side by side say nothing about which is which, and
	left and right are the one thing a person has to be sure of here. The
	point says it twice over: by colour - cyan and pink, what the canvas
	draws those two walls in - and by aiming out at the sidebearing the
	controls beside it edit.
	"""

	def drawRect_(self, rect):
		# UNDER THIS VIEW'S APPEARANCE, not the application's, which is dark:
		# the section is pinned to the light one, as Glyphs pins its own info
		# box, and a semantic colour asked for outside a drawing appearance
		# answers for the app instead.
		try:
			appearance = self.effectiveAppearance()
			if hasattr(appearance, 'performAsCurrentDrawingAppearance_'):
				appearance.performAsCurrentDrawingAppearance_(self.paint)
			else:
				self.paint()
		except Exception:
			log(f'PillView error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def paint(self):
		try:
			# THE POINT IS DRAWN FIRST AND COVERED. Its base runs up the edge the
			# slab sits against, so the slab laid over it hides the base and
			# leaves the part that sticks out - which saves unioning two paths
			# into one outline that would have to round its own corners.
			#
			# INSIDE THE BOUNDS, not hanging off them: a view clips its drawing
			# to its own frame, so the room for the point is left by the layout's
			# outer margin rather than taken from the neighbour.
			bounds = self.bounds()
			width, height = bounds.size.width, bounds.size.height
			far = getattr(self, 'isLeftSide', True)
			base = PILL_POINT if far else width - PILL_POINT
			# ONLY THE TIP IS ROUNDED. The two corners where the point meets the
			# slab are left mitred, and the slab's own edge on that side is left
			# square, so a flat base meets a flat edge and the two read as one
			# shape instead of a blob parked next to a box.
			#
			# HALF A POINT OF OVERLAP under the slab, so the seam between them
			# cannot show a hairline of whatever is behind through the
			# antialiasing.
			seam = base + 0.5 if far else base - 0.5
			(NSColor.systemCyanColor() if far else NSColor.systemPinkColor()).set()
			roundedPath(
				(NSPoint(seam, 0.0),
					NSPoint(0.0 if far else width, height / 2.0),
					NSPoint(seam, height)),
				(0.0, PILL_TIP, 0.0)).fill()
			outer = width if far else 0.0
			NSColor.windowBackgroundColor().set()
			roundedPath(
				(NSPoint(base, 0.0), NSPoint(outer, 0.0),
					NSPoint(outer, height), NSPoint(base, height)),
				(0.0, PILL_RADIUS, PILL_RADIUS, 0.0)).fill()
		except Exception:
			log(f'PillView error: {traceback.format_exc()}', error=True)


class PillGroup(vanilla.Group):
	nsViewClass = PillView


def setPreviewGear(button, on):
	"""The gear on the preview's menu button, dimmed when it shows nothing.

	The menu inside says which of the two are on; the button only has to say
	whether anything is, which it can do without a word on it. SF Symbols has
	no struck-through gear to say it with, so it is said with the ink.

	THE SAME GEAR AS THE OTHER MENU BUTTON, drawn the same way: filled, on its
	own, on a button of the same size and bezel. Two buttons that open two
	menus and are told apart by their bezel are two kinds of thing to a reader
	who only has to learn one.
	"""
	try:
		image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
			GEAR_SYMBOL, None)
		if image is not None:
			native = button.getNSButton()
			native.setImage_(image)
			native.setImagePosition_(NSImageOnly)
			native.setAlphaValue_(1.0 if on else 0.4)
	except Exception:
		log(f'setPreviewGear error: {traceback.format_exc()}', error=True)
