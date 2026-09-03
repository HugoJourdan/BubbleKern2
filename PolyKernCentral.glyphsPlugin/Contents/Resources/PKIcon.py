# encoding: utf-8
"""Sizing a piece of artwork to sit beside icons that are not artwork.

A PDF page is whatever the mark happened to be drawn on: the margins are an
accident of the export, and two files exported the same day can carry different
ones. Nothing in the file says where the marks sit on the page, so the only way
to find them is to draw the thing and look - which is what `inkBounds` does,
and why neither the tool's toolbar nor the window's has to be tuned by hand
when the artwork is redrawn.

Its own module because both toolbars need it: the tool's icon among the Glyphs
tools, and the Kerner's among the SF Symbols in this plugin's own window.
"""

from Cocoa import (
	NSBitmapImageRep,
	NSCalibratedRGBColorSpace,
	NSCompositingOperationSourceOver,
	NSGraphicsContext,
	NSImage,
	NSMakeRect,
	NSMakeSize,
)

# HOW HARD TO LOOK FOR INK. The scan is at SCALE times the artwork's own points
# so a hairline is not missed between samples, and anything at or under FLOOR
# out of 255 is the antialiasing of an edge rather than the edge.
INK_SEARCH_SCALE = 4
INK_SEARCH_FLOOR = 8
# NO CANVAS BY DEFAULT: the icon comes out the size of the mark. Pass one to
# have the mark centred on a square of that size instead.
ICON_CANVAS = 0.0


def inkBounds(image):
	"""The part of `image` that actually has ink in it, in points.

	A PDF page is whatever the artwork happened to be drawn on and nothing
	in the file says where the marks sit on it, so the only way to find
	them is to draw the thing and look. -> NSRect, or None if it is blank.
	"""
	size = image.size()
	scale = INK_SEARCH_SCALE
	wide, high = int(round(size.width * scale)), int(round(size.height * scale))
	if wide < 1 or high < 1:
		return None
	rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
		None, wide, high, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
	if rep is None:
		return None
	context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
	if context is None:
		return None
	NSGraphicsContext.saveGraphicsState()
	try:
		NSGraphicsContext.setCurrentContext_(context)
		# an empty `fromRect` means all of it
		image.drawInRect_fromRect_operation_fraction_(
			NSMakeRect(0, 0, wide, high), NSMakeRect(0, 0, 0, 0),
			NSCompositingOperationSourceOver, 1.0)
	finally:
		NSGraphicsContext.restoreGraphicsState()

	stride, samples = rep.bytesPerRow(), rep.samplesPerPixel()
	data = bytes(rep.bitmapData()[:stride * high])
	floor = INK_SEARCH_FLOOR
	left, right, top, bottom = wide, -1, high, -1
	for y in range(high):
		row = data[y * stride:y * stride + wide * samples]
		alpha = row[samples - 1::samples]  # RGBA, so alpha is the last one
		if max(alpha) <= floor:
			continue
		if y < top:
			top = y
		bottom = y
		x = 0
		while alpha[x] <= floor:  # the row has ink, so this cannot run off
			x += 1
		if x < left:
			left = x
		x = wide - 1
		while alpha[x] <= floor:
			x -= 1
		if x > right:
			right = x
	if right < 0:
		return None
	# bitmap rows run down from the top; a PDF's y runs up from the bottom
	return NSMakeRect(
		left / scale,
		size.height - (bottom + 1) / scale,
		(right - left + 1) / scale,
		(bottom - top + 1) / scale)

def trimmedIcon(image, height, canvas=None):
	"""`image`'s ink, `height` points tall, centred on a square `canvas`.

	The canvas is what does the centring - see TOOLBAR_ICON_CANVAS. It is
	never smaller than the mark, so an oversized `height` widens the canvas
	rather than cropping.

	Drawn on demand rather than baked into a bitmap, so the artwork stays
	vector and stays sharp at whatever the screen asks for.
	"""
	if canvas is None:
		canvas = ICON_CANVAS
	ink = inkBounds(image)
	if ink is None or not ink.size.height:
		return None
	scale = height / ink.size.height
	wide = ink.size.width * scale
	size = NSMakeSize(max(canvas, wide), max(canvas, height))
	# where the mark goes on that canvas, in the canvas's own points
	box = NSMakeRect((size.width - wide) / 2.0, (size.height - height) / 2.0,
			wide, height)

	def drawInk(rect):
		# `rect` is wherever the icon is being drawn, which need not be the
		# size the canvas was cut at, so put the mark on it proportionally
		across = rect.size.width / size.width
		down = rect.size.height / size.height
		image.drawInRect_fromRect_operation_fraction_(
			NSMakeRect(rect.origin.x + box.origin.x * across,
					rect.origin.y + box.origin.y * down,
					box.size.width * across, box.size.height * down),
			ink, NSCompositingOperationSourceOver, 1.0)
		return True

	icon = NSImage.imageWithSize_flipped_drawingHandler_(size, False, drawInk)
	if icon is None:  # no drawing handler on this macOS: bake it instead
		icon = NSImage.alloc().initWithSize_(size)
		icon.lockFocus()
		try:
			drawInk(NSMakeRect(0, 0, size.width, size.height))
		finally:
			icon.unlockFocus()
	return icon
