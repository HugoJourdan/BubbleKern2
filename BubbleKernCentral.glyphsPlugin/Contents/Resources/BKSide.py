# encoding: utf-8
"""Which of a glyph's two sides a piece of code is talking about.

A SUBCLASS OF `str`, AND THE STRING IS THE LETTER - `L` and `R` are what the
file itself writes. So a side works anywhere the letter did: as a dict key,
interpolated into a message, concatenated. See CLAUDE.md.

NO IMPORTS AT THE TOP ON PURPOSE. `BKAutoBubble` takes its `LEFT` and `RIGHT`
from here and is otherwise pure - it runs, and is tested, without Glyphs or
AppKit - so the one AppKit name needed is looked up inside `color()` instead.
"""


class Side(str):
	"""One of a glyph's two sides, and everything that follows from which one.

	>>> LEFT.key('Nodes')
	'BubbleKernNodesL'
	"""

	def __new__(cls, letter, isLeft, tempKey, defaultKey, colorName):
		side = str.__new__(cls, letter)
		side.isLeft = isLeft
		# What the layer's tempData cache calls this side's nodes, and the flag
		# saying the cache made them up rather than read them.
		side.tempKey = tempKey
		side.defaultKey = defaultKey
		side.colorName = colorName
		return side

	def key(self, concept):
		"""The userData key this side keeps `concept` under. -> str

		`Nodes`, `Refer`, `Mirror`, `Box`, `Auto`, `Export` - the six the file
		format has. Never build one by hand.
		"""
		return 'BubbleKern' + concept + str(self)

	def origin(self, layer):
		"""Where this side measures its x values from. -> float

		The left wall is stored against the origin and the right one against
		the advance, so that a spacing change moves the right wall with it.
		"""
		return 0 if self.isLeft else layer.width

	def color(self):
		"""The colour the canvas draws this wall in. -> NSColor

		Imported here rather than at the top: see the module docstring.
		"""
		from AppKit import NSColor
		return getattr(NSColor, self.colorName)()

	@property
	def other(self):
		"""The side this one is not. -> Side"""
		return RIGHT if self.isLeft else LEFT

	def __repr__(self):
		return "Side('%s')" % str(self)


LEFT = Side('L', True, 'nodesL', 'defaultL', 'systemCyanColor')
RIGHT = Side('R', False, 'nodesR', 'defaultR', 'systemPinkColor')
SIDES = (LEFT, RIGHT)


def of(isLeft):
	"""The side a boolean means. -> Side

	For the many callers that still say `isLeft`. A side is not a boolean -
	there is nothing true about the left one - but the signatures are older
	than this module and rewriting them all at once buys less than it risks.
	"""
	return LEFT if isLeft else RIGHT
