# encoding: utf-8
"""A word on a band across the corner of a pane.

The font export writes a table nothing shipping reads yet, and the pane says so
in a paragraph - which is a thing read once and then never again. A ribbon says
it before anything else in the pane has been looked at, and goes on saying it.

Its own module because it is a view: it knows a word and a corner, and nothing
about what it is warning anybody off.
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
	NSFontWeightBold,
	NSForegroundColorAttributeName,
	NSGraphicsContext,
	NSKernAttributeName,
	NSPoint,
	NSView,
)

from PKCommonLogic import log

# THE BAND, MEASURED FROM THE CORNER ALONG BOTH EDGES. The size is the square
# the whole thing needs, so it is never less than OUTER. What the band can hold
# is the distance between its ends: the centre line runs from (SIZE - centre,
# SIZE) to (SIZE, SIZE - centre) and is centre * sqrt(2) long, which for these
# numbers is 58 points - room for a short word at 11pt bold and a little air.
RIBBON_SIZE = 76.0
RIBBON_INNER = 26.0
RIBBON_OUTER = 56.0
RIBBON_TEXT = 11.0
RIBBON_TRACKING = 1.6


class PKRibbonView(NSView):
	"""A diagonal band across this view's top right corner, with a word on it.

	Prefixed because an ObjC class name is process-global and Glyphs loads
	every plugin into one runtime.

	Carries `_word`, assigned through `setWord`.
	"""

	@objc.python_method
	def setWord(self, word):
		self._word = word
		self.setNeedsDisplay_(True)

	def hitTest_(self, point):
		# NOTHING TO CLICK, AND NOTHING BEHIND IT TO BLOCK. It lies over the
		# corner of a pane; a view that swallowed clicks there would be a
		# mystery to whoever hit it.
		return None

	def drawRect_(self, rect):
		try:
			appearance = self.effectiveAppearance()
			if hasattr(appearance, 'performAsCurrentDrawingAppearance_'):
				appearance.performAsCurrentDrawingAppearance_(self.paint)
			else:
				self.paint()
		except Exception:
			log(f'PKRibbonView error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def paint(self):
		try:
			far = float(self.bounds().size.width)  # square: the corner is (far, far)
			band = NSBezierPath.bezierPath()
			band.moveToPoint_(NSPoint(far - RIBBON_OUTER, far))
			band.lineToPoint_(NSPoint(far - RIBBON_INNER, far))
			band.lineToPoint_(NSPoint(far, far - RIBBON_INNER))
			band.lineToPoint_(NSPoint(far, far - RIBBON_OUTER))
			band.closePath()
			NSColor.systemOrangeColor().set()
			band.fill()
			word = getattr(self, '_word', None)
			if not word:
				return
			label = NSAttributedString.alloc().initWithString_attributes_(word, {
				NSFontAttributeName: NSFont.systemFontOfSize_weight_(
					RIBBON_TEXT, NSFontWeightBold),
				# BLACK, NOT A LABEL COLOUR. The band is orange whatever the
				# window is set to, so a colour that flips with the appearance
				# would go white on orange half the time.
				NSForegroundColorAttributeName:
					NSColor.blackColor().colorWithAlphaComponent_(0.8),
				NSKernAttributeName: RIBBON_TRACKING,
			})
			size = label.size()
			# THE MIDDLE OF THE BAND, AND THE DIAGONAL IT RUNS ALONG. The
			# centre line goes from (far - centre, far) down to (far, far -
			# centre), so its midpoint is half of centre in from both edges
			# and its direction is 45 degrees clockwise of the x axis.
			centre = (RIBBON_INNER + RIBBON_OUTER) / 2.0
			NSGraphicsContext.currentContext().saveGraphicsState()
			try:
				transform = NSAffineTransform.transform()  # NOT NSAffineTransform()
				transform.translateXBy_yBy_(far - centre / 2.0, far - centre / 2.0)
				transform.rotateByDegrees_(-45.0)
				transform.concat()
				label.drawAtPoint_(NSPoint(-size.width / 2.0, -size.height / 2.0))
			finally:
				NSGraphicsContext.currentContext().restoreGraphicsState()
		except Exception:
			log(f'PKRibbonView paint error: {traceback.format_exc()}', error=True)
