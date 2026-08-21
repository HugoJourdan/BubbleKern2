# THE TOOL BASED ON SELECTTOOL FOR EDITING BUBBLES.

import objc
import traceback
import math
from math import radians, tan, hypot
import vanilla
from GlyphsApp import Glyphs, GSLayer, GSControlLayer, GSCallbackHandler, distance, addPoints, UPDATEINTERFACE, DRAWINACTIVE # , DRAWBACKGROUND
from GlyphsApp.plugins import SelectTool

from Cocoa import (
	NSObject,
	NSFont,  # for the captions drawn on the canvas
	# NSMenuItem,  # for contextual menu item
	NSColor,  # for highlighting in draw calls
	NSFocusRingTypeNone,  # the coordinate fields carry no halo
	NSBezierPath,  # for many things
	NSPoint,  # for many things
	# NSRect,  # to get the circular dot for drawing nodes
	NSMakeRect,  # to get the circular dot for drawing nodes
	# NSSize, # doesn't seem to be used
	# NSEventModifierFlagDeviceIndependentFlagsMask,  # for doing stuff in mouseDown_() and keyDown_()
	# NSEventModifierFlagShift,  # for doing stuff in mouseDown_() and keyDown_()
	NSEventModifierFlagShift, NSEventModifierFlagCommand, NSEventModifierFlagOption,  # for doing stuff in mouseDown_() and keyDown_()
	NSEventModifierFlagControl,  # so a shortcut is not mistaken for typing
	# NSAlert,
	# NSAlertStyleCritical,
	NSNotificationCenter,  # for undo notification
	NSView,  # for the settings-window preview
	NSAppearance,  # so the preview draws in the window's appearance
	NSPasteboard,  # for copying the settings as a custom parameter
	NSPasteboardTypeString,
	NSMenu,  # for the settings button's menu
	NSMenuItem,
	NSStackView,  # the row Glyphs keeps the info box in
	NSImage,  # the gear on the preview's own switches
	NSImageOnly,  # the gear is the whole of both menu buttons
)

from Foundation import NSTimer  # to keep asking for the info box until the bar is up
from Foundation import NSOperationQueue  # to print after the menu has let go

from typing import Self

from BKCommonLogic import getFinalBubble, tempToUserNodeX, show_alert, log, isReferenceValid, isMirrored, isStale, needsGenerating, isAuto, recordBox, shiftBubbleForSpacing, MIRROR_TOKEN, AUTO_TOKEN
import BKAutoBubble as auto
import BKPreview as preview
from BKGroupGrid import BKGroupGridView
from BKSide import LEFT, RIGHT, SIDES, of
from BKFields import CompletingEditText, NudgeEditText
import BKBubbleStore as store
from BKInfoBox import (GEAR_SYMBOL, PILL_POINT, InspectorGroup, PillGroup,
	setPreviewGear)
from BKCommonLogic import getKernValue


def soon(work):
	"""Wrap a menu item's callback so the work happens once the menu lets go.

	Canvas work inside a menu action deadlocks AppKit's menu tracking; one turn
	of the run loop later the menu has let go. See CLAUDE.md.
	"""
	def later(sender=None):
		def run():
			try:
				work()
			except Exception:
				log(f'menu action error: {traceback.format_exc()}', error=True)
		NSOperationQueue.mainQueue().addOperationWithBlock_(run)
	return later


def report(message):
	"""Say what happened in the Macro window, on the next turn of the run loop.

	NEVER `print` STRAIGHT FROM A MENU ITEM'S ACTION - it deadlocks AppKit's menu
	tracking (see CLAUDE.md). `log` is safe either way: it goes through `logging`,
	nowhere near the Macro panel.
	"""
	def say():
		try:
			print(f'BubbleKern: {message}')
		except Exception:
			log(f'report error: {traceback.format_exc()}', error=True)
	NSOperationQueue.mainQueue().addOperationWithBlock_(say)


# constants
fontSize = 12
clickRadius = 10
# The wash inside an unselected node's ring: enough to read as a disc rather
# than a hole in the wall, not enough to compete with the wall itself.
NODE_FILL_ALPHA = 0.2
TempDataBubblesKey = "bubbles"
# WHAT A BORROWING LAYER WAS HANDED WHEN ITS CACHE WAS FILLED. A composite
# owns no wall, so what sits in its tempData came from its components; keeping
# a copy is how the cache can tell 'nobody has touched this' from 'the glyph I
# borrowed it from has moved', which are the same difference to a bare compare.
TempDataBorrowedKey = 'borrowed'
# THE SAME FOUR NAMES THE SIDE CARRIES, so the cache is spelled in one place.
# Kept as constants because plenty of code here means one PARTICULAR side and
# reads better saying so than indexing SIDES.
TempDataLeftNodesKey = LEFT.tempKey
TempDataLeftIsDefaultKey = LEFT.defaultKey
TempDataRightNodesKey = RIGHT.tempKey
TempDataRightIsDefaultKey = RIGHT.defaultKey
class BubbleNode(NSObject):

	_position: NSPoint = NSPoint(0, 0)
	selected: bool = False

	@objc.typedSelector(b"{CGPoint=dd}@:")
	def position(self):
		return self._position

	@objc.typedSelector(b"v@:{CGPoint=dd}")
	def setPosition_(self, position):
		self._position = position

	@property
	def pos(self):
		return self._position

	@pos.setter
	def pos(self, pos):
		self._position = pos

	@property
	def x(self):
		return self._position.x

	@property
	def y(self):
		return self._position.y

	def __repr__(self):
		return f"(BubbleNode(0x{id(self):x}) x={self.pos.x}, y={self.pos.y})"

	def description(self):
		return f"(BubbleNode(0x{id(self):x}) x={self.pos.x}, y={self.pos.y})"

	def parent(self):
		return None

	def copy(self) -> Self:
		copy = self.__class__.new()
		copy.pos = self._position
		return copy

# THE INVERSE OF tempToUserNodeX: STORED (UPRIGHT) X BACK TO CANVAS X.
# SNAPPING HAPPENS ON THE STORED X, SO A GRID STAYS A GRID ON AN ITALIC
# INSTEAD OF SAMPLING THE SLANTED X.
def userToTempNodeX(x, y, italicAngle, xHeight):
	if italicAngle != 0:
		return x - (y - xHeight / 2) / tan(radians(90 + italicAngle))
	return x


def makeBubbleNode(x, y, italicAngle, xHeight):
	node = BubbleNode.alloc().init()
	newX = userToTempNodeX(x, y, italicAngle, xHeight)
	node.setPosition_(NSPoint(round(newX), round(y)))
	return node


# USED TO CHECK IF NODE IS CLICKABLE.
def nearNodes(point0, point1, threshold):
	d = distance(point0, point1)
	return d <= threshold

# ONLY USED IN closestToNodes
def closest_point_on_segment(A: BubbleNode, B: BubbleNode, P: NSPoint):  # A=node0, B=node1, P=clicked point
	x1, y1 = A.pos.x, A.pos.y
	x2, y2 = B.pos.x, B.pos.y
	x0, y0 = P.x, P.y
	dx = x2 - x1  # s distance
	dy = y2 - y1  # y disance

	if dx == 0 and dy == 0:  # A and B are the same point
		return A.pos.x, A.pos.y
	# Projection parameter t
	t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
	# Clamp to segment
	t = max(0, min(1, t))
	# Closest point
	closest_x = x1 + t * dx
	closest_y = y1 + t * dy

	return closest_x, closest_y

# FOR CHECKING IF mousePos ADDS A NEW NODE.
# CHECKS IF mousePos IS ON THE SERIES OF SEGMENTS COMPOSED OF 'NODES'.
# ASSUMES 'NODES' STARTS FROM BOTTOM
def closestToNodes(nodes: list[BubbleNode], mousePos: NSPoint):
	if not nodes:
		return None  # a side with no wall has nothing to add a node to
	if nodes[-1].pos.y < mousePos.y:  # if cursor is too far above the bubble
		return nodes[-1].pos.x, nodes[-1].pos.y
	elif nodes[0].pos.y > mousePos.y:  # if too far below the bubble
		return nodes[0].pos.x, nodes[0].pos.y
	else:
		for i, n in enumerate(nodes):
			if n != nodes[-1]:
				if n.pos.y <= mousePos.y <= nodes[i + 1].pos.y:  # mousePos Y is between these two nodes
					return closest_point_on_segment(n, nodes[i + 1], mousePos)
	return None

# FOR DISPLAYING COORDFINATES. RETURNS ITALIC-OFFSET X VALUE FOR A GIVEN NODE.
FIT_TEXT = 'HOLTAVOAvonTox'
# How far above the info box this tool's section floats.
INFO_BOX_GAP = 6.0
# The margin between a slab's edge and what it holds. The tag's point is
# extra, on the outer edge only.
SLAB_MARGIN = 6
# The refresh button sits a point tighter than that on both of its sides: it
# is a symbol with its own air around it, where a field is ink to its border.
BUTTON_MARGIN = SLAB_MARGIN - 1


# before ⇧ finishes the job. Deliberately small: magnetism that reaches far
# takes the hand's answer away and gives back its own.
MAGNET_POINTS = 6.0


mainDrawingHandler = None
bubbleDrawingIsActive = False  # True if I want to draw all the time

class BubbleKernTool(SelectTool):
	bubbles: dict[str, list[BubbleNode]]

	@objc.python_method
	def settings(self):
		global mainDrawingHandler
		if mainDrawingHandler is None:
			mainDrawingHandler = self
			GSCallbackHandler.addCallback_forOperation_(mainDrawingHandler, DRAWINACTIVE)

		self.name = Glyphs.localize({
			"en": "BubbleKern Tool",
		})
		self.keyboardShortcutModifier = (NSEventModifierFlagCommand | NSEventModifierFlagShift | NSEventModifierFlagOption)
		self.keyboardShortcut = 'b'
		self.toolbarPosition = 20
		self.horizontal = getattr(self, "horizontal", True)  # whether horizontal or vertical bubbles
		self.closestNode = None  # for highlighting the addable node
		self.closestNodeSide = None
		self.selectableNode = None  # for highlighting the selectable node
		# USER INTERFACE
		self.w = vanilla.Window((360, 10))
		self.buildInfoSection()
		self.buildCoordsSlab()
		self.applyInfoBarAppearance()
		self.inspectorDialogView = True
		# / USER INTERFACE

	@objc.python_method
	def buildInfoSection(self):
		"""The two slabs: a reference field and a generate button a side."""
		# TWO SLABS, NOT ONE BOX WITH A LINE DOWN IT: each striped in the colour
		# the canvas draws that wall in.
		self.w.group = vanilla.Group("auto")
		# BEFORE THE CONTROLS, so the controls land in front of them: vanilla
		# adds subviews in the order the attributes are set.
		self.w.group.boxL = PillGroup("auto")
		self.w.group.boxR = PillGroup("auto")
		self.w.group.boxL.getNSView().isLeftSide = True
		self.w.group.boxR.getNSView().isLeftSide = False
		self.w.group.glyphNameL = CompletingEditText('auto', '', callback=self.infoBox, placeholder='Refer to glyph')
		self.w.group.glyphNameR = CompletingEditText('auto', '', callback=self.infoBox, placeholder='Refer to glyph')
		f0 = self.w.group.glyphNameL.getNSTextField()
		f1 = self.w.group.glyphNameR.getNSTextField()
		for field in (f0, f1):
			field.setToolTip_('A glyph to take this side from, %s for the '
				'other side of this glyph, or %s to have this side drawn from '
				'the outline and redrawn whenever it moves'
				% (MIRROR_TOKEN, AUTO_TOKEN))
		f0.setNextKeyView_(f1)
		f1.setNextKeyView_(f0)
		# ONE BUTTON, ONE COMMAND. The menu behind these held two items and
		# then one; a menu whose whole content is the thing you came for is a
		# click spent asking. Decompose moved to the canvas's own menu, where
		# it can appear only on a side that has something to decompose.
		#
		# NOT DEFERRED, unlike the menu items this replaces: a button's action
		# comes from an ordinary click, with no tracking session still winding
		# up behind it.
		for name, isLeft in (('menusL', True), ('menusR', False)):
			button = vanilla.SquareButton('auto', '',
				callback=(lambda sender, side=isLeft: self.autoGenerate(side)),
				sizeStyle='small')
			setattr(self.w.group, name, button)
			native = button.getNSButton()
			native.setToolTip_('Auto-generate this side\u2019s bubble')
			# NO BEZEL. The slab it sits on is already a shape with an edge, and
			# a second edge inside it reads as a box in a box. The symbol alone
			# is the whole button, so it borrows the slab's ground.
			native.setBordered_(False)
			image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
				'arrow.counterclockwise', 'Auto-generate')
			if image is not None:
				native.setImage_(image)
		rules = (
			# The two slabs split the width evenly, and the run of controls is
			# symmetrical about the gap between them, so each slab ends up
			# exactly around the three things that belong to its side.
			'H:|[boxL(boxR)]-(gap)-[boxR]|',
			# A FLOOR UNDER THE WIDTH, at a priority below required so a window
			# with no room for it bends the rule instead of breaking.
			# MIRRORED, NOT REPEATED. The left slab runs button-then-field and
			# the right one field-then-button, so each button sits against its
			# own slab's pointed edge and the two fields meet in the middle.
			'H:|-(edgeL)-[menusL(button)]-(spL)-[glyphNameL(glyphNameR,>=100@750)]'
			'-(between)-[glyphNameR]-(sp)-[menusR(button)]-(edge)-|',
			'V:|[boxL]|',
			'V:|[boxR]|',
			'V:|-(pad)-[glyphNameL(row)]-(pad)-|',
			# A POINT LOWER THAN THE FIELDS. The symbol's ink sits high in its
			# box, so a button squared up with the fields reads as riding above
			# them; `drop` and `rise` are `pad` moved one point down.
			'V:|-(drop)-[menusL(row)]-(rise)-|',
			'V:|-(pad)-[glyphNameR(row)]-(pad)-|',
			'V:|-(drop)-[menusR(row)]-(rise)-|',
		)
		# `edge` is the outer margin, the tag's point plus the slab's own margin;
		# `between` is one slab's margin, the gap, and the other's, so the two
		# refresh buttons sit the same distance from their slab's edge. The gap
		# between the slabs is the gap under them, so the section reads as one
		# thing with the info box.
		#
		# NOT QUITE A MIRROR: `edgeL` sets the left button a point further out
		# than the right one's reflection would, which is what the pair looks
		# level at. The point comes off its outer gap and goes straight back
		# into `spL`, the gap on its other side. See CLAUDE.md.
		metrics = {'pad': 6, 'drop': 7, 'rise': 5, 'sp': 2, 'spL': 3,
				'edge': PILL_POINT + BUTTON_MARGIN,
				'edgeL': PILL_POINT + BUTTON_MARGIN - 1, 'gap': INFO_BOX_GAP,
				'between': INFO_BOX_GAP + 2 * SLAB_MARGIN,
				'button': 20, 'row': 22}
		self.w.group.addAutoPosSizeRules(rules, metrics)

	@objc.python_method
	def buildCoordsSlab(self):
		"""The X and Y of the selected node, in its own slab."""
		# THE SELECTED NODE'S COORDINATES, IN A STRIP OF ITS OWN. Glyphs' own X
		# and Y box only ever shows a GSNode, and a bubble node is not ink and
		# must never become ink to get a box, so it cannot appear there however
		# node-like it is made. See CLAUDE.md.
		#
		# ABOVE THE ROW, NOT IN IT: that row is two slabs symmetrical about the
		# middle of the box below, and a third thing on one end of it would say
		# the middle was somewhere else.
		# X OVER Y, LABEL THEN NUMBER, the way Glyphs stacks the same two
		# numbers - and in its own slab, in the place it puts it: hard against
		# the right of the info box, standing on the same line.
		self.w.coords = InspectorGroup('auto')
		# THE SIZE THE REST OF THE BAR IS SET IN. `small` is 11pt against the
		# 13 of every number beside it, and a readout that has to be leaned
		# into to read is worse than no readout in a box this size.
		self.w.coords.xLabel = vanilla.TextBox('auto', 'X', alignment='right')
		self.w.coords.x = vanilla.EditText('auto', '', callback=self.coordEdited)
		self.w.coords.yLabel = vanilla.TextBox('auto', 'Y', alignment='right')
		self.w.coords.y = vanilla.EditText('auto', '', callback=self.coordEdited)
		# NO BOX ROUND THE NUMBERS. The slab is the edge; Glyphs' own fields
		# draw none until they are being typed in.
		for control in (self.w.coords.x, self.w.coords.y):
			native = control.getNSTextField()
			native.setBordered_(False)
			native.setDrawsBackground_(False)
			native.setFocusRingType_(NSFocusRingTypeNone)
			# MONOSPACED, LIKE THE CARD AGAINST THE NODE: proportional digits
			# move the whole number under itself as a node passes through -9,
			# -10, -100. The label beside it is a word and stays in the face
			# the rest of the bar is set in.
			native.setFont_(NSFont.monospacedSystemFontOfSize_weight_(
				NSFont.systemFontSize(), 0.0))
		for control in (self.w.coords.xLabel, self.w.coords.yLabel):
			control.getNSTextField().setTextColor_(NSColor.secondaryLabelColor())
		self.w.coords.addAutoPosSizeRules((
			'H:|-(edge)-[xLabel(label)]-(sp)-[x(field)]-(right)-|',
			'H:|-(edge)-[yLabel(label)]-(sp)-[y(field)]-(right)-|',
			'V:|-(top)-[xLabel(row)]-(gap)-[yLabel(row)]-(pad)-|',
			'V:|-(top)-[x(row)]-(gap)-[y(row)]-(pad)-|',
			# GLYPHS' OWN X AND Y BOX, MEASURED IN THE RUNNING APP: a slab 78 by
			# 46, labels 13 wide standing at x 8, and fields 53 wide at x 21,
			# both rows 17 tall at y 3 and y 24. Four short of the frames they
			# make, because vanilla lays out the ALIGNMENT rect and a text
			# field's frame stands two points past it a side. See CLAUDE.md.
		), {'edge': 10, 'sp': 4, 'top': 5, 'gap': 4, 'pad': 3, 'right': 6,
			'label': 9, 'field': 49, 'row': 17})

	@objc.python_method
	def applyInfoBarAppearance(self):
		"""Hide the coordinate slab and light both, whatever the theme."""
		self.coordsView = self.w.coords.getNSView()
		self.coordsView.setHidden_(True)
		self.infoBoxView = self.w.group.getNSView()
		# LIGHT, WHATEVER THE THEME. Glyphs' own info box is a light grey slab
		# in dark mode too, and these sit beside it: left to inherit the
		# canvas's dark appearance the fields would come out dark on light.
		aqua = NSAppearance.appearanceNamed_('NSAppearanceNameAqua')
		if aqua is not None:
			self.infoBoxView.setAppearance_(aqua)
			self.coordsView.setAppearance_(aqua)

	@objc.python_method
	def start(self):  # WHEN GLYPHSAPP STARTS
		pass

	# @objc.python_method
	@objc.python_method
	def infoBoxDecoy(self):
		"""The empty view Glyphs is given instead of the real section.

		Made once and kept: it is the thing Glyphs owns, moves and re-adds, and
		it is hidden, so NSStackView leaves it out of the bar's layout
		altogether. It also says where the bar IS, which is the only thing this
		tool still needs from it.
		"""
		anchor = getattr(self, 'infoBoxAnchor', None)
		if anchor is None:
			anchor = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
			anchor.setHidden_(True)
			self.infoBoxAnchor = anchor
		return anchor

	@objc.python_method
	def infoBoxContainer(self):
		"""Glyphs' own info box, found through the decoy sitting beside it."""
		stack = self.infoBoxDecoy().superview()
		if not isinstance(stack, NSStackView):
			return None
		for sub in (stack.arrangedSubviews() or []):
			if 'GSInfoViewContainer' in sub.__class__.__name__:
				return sub
		return None

	@objc.python_method
	def placeInfoBox(self):
		"""Park the section above the info box and leave it there.

		Glyphs rebuilds the info bar's stack about 150ms after the interface
		update that caused it, so anything moved out of that stack is moved
		back. Glyphs is given a decoy to own and the real section is parented
		once, straight into the canvas, held above the info box by two
		constraints. See CLAUDE.md.

		Cheap enough for `view`, which is called constantly: two identity
		checks when it is already where it belongs.
		"""
		try:
			view = getattr(self, 'infoBoxView', None)
			if view is None:
				return
			box = self.infoBoxContainer()
			if box is None:
				return  # the bar is not up yet; the next call will find it
			host = box.superview()
			while host is not None and isinstance(host, NSStackView):
				host = host.superview()
			if host is None:
				return
			if (view.superview() is host
					and getattr(self, 'infoBoxAnchoredTo', None) is box):
				return
			# A NEW INFO BOX MEANS NEW CONSTRAINTS. Glyphs builds a fresh
			# container when it rebuilds the bar, and constraints against the
			# old one are dead the moment it goes.
			self.dropInfoBoxRules()
			view.removeFromSuperview()
			host.addSubview_(view)
			view.setTranslatesAutoresizingMaskIntoConstraints_(False)
			# CENTRED ON THE BOX BELOW, not lined up with its left edge: the
			# two are different widths, and a shared middle reads as "these
			# belong together" where a shared left edge reads as a column one
			# of them has fallen out of.
			rules = (
				view.centerXAnchor().constraintEqualToAnchor_(
					box.centerXAnchor()),
				view.bottomAnchor().constraintEqualToAnchor_constant_(
					box.topAnchor(), -INFO_BOX_GAP),
			)
			coords = getattr(self, 'coordsView', None)
			if coords is not None:
				# ONE STOREY UP, on the same middle as everything else here.
				coords.removeFromSuperview()
				host.addSubview_(coords)
				coords.setTranslatesAutoresizingMaskIntoConstraints_(False)
				# BESIDE THE BOX, NOT OVER IT: the spot Glyphs shows a node's own
				# X and Y in, which is free here because the tool keeps the outline
				# out of its selection and so no node of Glyphs' own is ever in it.
				# HARD AGAINST IT, WITH NO GAP AT ALL: the info bar's stack is
				# spaced zero, so the two slabs meet.
				rules = rules + (
					coords.leadingAnchor().constraintEqualToAnchor_(
						box.trailingAnchor()),
					coords.bottomAnchor().constraintEqualToAnchor_(
						box.bottomAnchor()),
				)
			for rule in rules:
				rule.setActive_(True)
			self.infoBoxRules = rules
			self.infoBoxAnchoredTo = box
		except Exception:
			log(f'placeInfoBox error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def placeInfoBoxSoon(self, tries=15):
		"""Keep asking until the bar is up.

		`view` is asked for the section BEFORE the decoy is in the stack, so the
		first attempt has nothing to anchor to and gives up. See CLAUDE.md.

		Bounded, and it stops the moment it lands - about a second of asking at
		the outside, and none of it if the first attempt works.
		"""
		try:
			self.placeInfoBox()
			if getattr(self, 'infoBoxAnchoredTo', None) is not None or tries <= 0:
				return

			def again(timer):
				# NOT AFTER THE TOOL HAS GONE, or a tool nobody is using puts
				# its section back on somebody else's canvas.
				if getattr(self, 'infoBoxLive', False):
					self.placeInfoBoxSoon(tries - 1)

			NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.08, False, again)
		except Exception:
			log(f'placeInfoBoxSoon error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def hideInfoBox(self):
		"""Take the section off the canvas, which deactivate does."""
		try:
			self.infoBoxLive = False
			self.dropInfoBoxRules()
			self.infoBoxAnchoredTo = None
			for name in ('infoBoxView', 'coordsView'):
				view = getattr(self, name, None)
				if view is not None:
					view.removeFromSuperview()
		except Exception:
			log(f'hideInfoBox error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def dropInfoBoxRules(self):
		"""Let go of the two constraints, if any are still held."""
		for rule in (getattr(self, 'infoBoxRules', None) or ()):
			try:
				rule.setActive_(False)
			except Exception:
				pass
		self.infoBoxRules = None

	def activate(self):  # When the tool is activated, updateUI and set activeLayer
		try:
			proceed = False
			initialise = False
			f = Glyphs.font

			# check if initial dialog is necessary
			use = f.tempData['useBubbleKern'] # if user has already clicked Yes or Cancel in the dialog
			if use == None: # if no pre-existing answer in userData
				use = f.userData['useBubbleKern']

			if use == True: # BubbleKern already in use
				proceed = True
			elif use == None: # on the first run per font file
				alertTitle = 'Starting BubbleKern'
				alertMessage = """Are you sure you want to use BubbleKern in this font?
				(You can remove font's Bubble data from Edit > BubbleKern Kerner)"""
				initialise = show_alert(message=alertTitle, secondMessage=alertMessage)
			elif use == False:
				Glyphs.showNotification("BubbleKern Tool", "If you want to use BubbleKern, please reopen the file.")

			if proceed or initialise: # standard proceed
				f.tempData['useBubbleKern'] = True
				f.userData['useBubbleKern'] = True
				Glyphs.addCallback(self.updateUI, UPDATEINTERFACE)
				self.infoBoxLive = True
				self.placeInfoBoxSoon()
				NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
					self, b'_undoDidComplete:', 'NSUndoManagerDidUndoChangeNotification', None
				)
				NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
					self, b'_undoDidComplete:', 'NSUndoManagerDidRedoChangeNotification', None
				)
				self.activeLayer = self.editViewController().activeLayer() if self.editViewController() is not None else None
			else: # Cancel has been clicked or use is already False, go to Select Tool
				f.tempData['useBubbleKern'] = False
				self.deactivate()
				f.tool = 'SelectTool'

			if initialise:
				for g in f.glyphs:
					for gl in g.layers:
						self.saveNodesToLayer(gl)
				self.loadNodesFromLayer(layer=self.activeLayer)

			# ANY PREVIEW KERNING RECORDED BUT NOT REMOVED - A SAVE WITH IT ON, A
			# CRASH, A REOPENED FILE - IS TAKEN OUT HERE BEFORE ANY IS WRITTEN.
			store.applyPreviewKerning(f)
		except Exception:
			log(f'activate error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def deactivate(self):  # When the tool is deactivated / went to font view
		Glyphs.removeCallback(self.updateUI, UPDATEINTERFACE)
		NSNotificationCenter.defaultCenter().removeObserver_name_object_(
			self, 'NSUndoManagerDidUndoChangeNotification', None
		)
		NSNotificationCenter.defaultCenter().removeObserver_name_object_(
			self, 'NSUndoManagerDidRedoChangeNotification', None
		)
		# THE PREVIEW KERNING BELONGS TO THIS TOOL. LEAVING IT TAKES IT BACK OUT,
		# WHICH IS ALSO THE ANSWER TO "WHAT IF I SAVE WITH IT ON": SWITCH TOOL
		# AND SAVE AGAIN.
		store.clearPreviewKerning()
		self.hideInfoBox()

	@objc.python_method
	def setActiveLayer(self):
		if self.editViewController() is None:
			return False
		elif self.editViewController().activeLayer() is None:
			return False
		elif isinstance(self.editViewController().activeLayer(), GSControlLayer):
			return False
		elif self.editViewController().activeLayer().name is None:
			return False
		else:
			self.activeLayer = self.editViewController().activeLayer()
			return True

	@objc.python_method
	def infoBox(self, sender):  # Called if Info Box UI elements are edited
		try:
			if self.setActiveLayer() is False:
				return
			self.saveInfoToLayer(self.activeLayer)
			self._updateReferenceFieldColors(self.activeLayer)
			Glyphs.redraw()
		except Exception:
			log(f'infoBox error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def updateUI(self, theEvent = None):  # Fill UI fields from userData after Interface change
		try:
			self.placeInfoBox()
			# Before the early return: an outline edit has to reach the preview
			# even when there is no active layer to fill the info box from.
			self.refreshPreview()
			if self.setActiveLayer() is False:
				return
			layer = self.activeLayer

			for side, field in zip(SIDES, (self.w.group.glyphNameL, self.w.group.glyphNameR)):
				if isMirrored(layer, side.isLeft):
					# A MIRRORED SIDE READS BACK AS WHAT WAS TYPED TO MAKE IT ONE.
					field.set(MIRROR_TOKEN)
					continue
				if isAuto(layer, side.isLeft):
					field.set(AUTO_TOKEN)
					continue
				value = layer.userData[side.key('Refer')]
				if (isinstance(value, str) and len(value) == 0) or not value:
					value = ''
				field.set(value)
			self._updateReferenceFieldColors(layer)
			self.followSpacing(layer)
			self.showCoordinates(layer)
			self.regenerateIfStale(layer)
		except Exception:
			log(f'updateUI error: {traceback.format_exc()}', error=True)

	def view(self):  # SHOWS INFO BOX; CALLED CONSTANTLY
		# RETURN NONE WHEN YOU WANT TO DISABLE INFO BOX
		#
		# GLYPHS GETS THE DECOY, not the section. Whatever this hands back is
		# put in the inspector stack and put back there on every rebuild; the
		# real section is parked on the canvas instead, where nothing moves it.
		self.placeInfoBox()
		return self.infoBoxDecoy()

	@objc.python_method
	def _updateReferenceFieldColors(self, layer):  # COLORS REFERENCE FIELDS RED IF REFERENCE IS INVALID
		if layer is None:
			return
		for side, field in zip(SIDES, (self.w.group.glyphNameL, self.w.group.glyphNameR)):
			gName = layer.userData.get(side.key('Refer')) or None
			tf = field.getNSTextField()
			if gName and not isReferenceValid(layer, side):
				tf.setTextColor_(NSColor.systemRedColor())
			else:
				tf.setTextColor_(NSColor.textColor())

	@objc.python_method
	def saveInfoToLayer(self, layer):  # CALLED AFTER UI CHANGE. SAVES THE REFERENCE FIELDS TO LAYER USERDATA
		try:
			if layer is None or layer.name is None:
				return

			# SAVE INTERFACE'S GLYPH NAMES FOR L AND R
			for side, value in zip(SIDES, (self.w.group.glyphNameL.get(), self.w.group.glyphNameR.get())):
				if isinstance(value, str):
					value = value.strip()
				if not value:
					value = None
				if value == MIRROR_TOKEN:
					# THE OTHER SIDE OF THIS GLYPH, spelled the way Glyphs'
					# metric keys spell it. Everything a mirror needs undoing
					# or clearing is in syncBubble already.
					self.syncBubble(side.isLeft, layers=[layer])
					continue
				if isinstance(value, str) and value.lower() == AUTO_TOKEN:
					self.setAuto(side.isLeft, layer)
					continue
				# ANYTHING ELSE TYPED TAKES THE SIDE OFF AUTOMATIC, including
				# emptying the field: what is drawn now stays drawn.
				for stale in (side.key('Auto'), side.key('Mirror')):
					if layer.userData[stale]:
						del layer.userData[stale]
				if layer.userData[side.key('Refer')] is not value:
					# IF USERDATA AND UI FIELD DISAGREE, DELETE TEMP DATA
					del layer.tempData[TempDataBubblesKey]

				if value:  # SAVE
					layer.userData[side.key('Refer')] = value
				else:  # REMOVE REFERENCE IF UI IS EMPTY
					del layer.userData[side.key('Refer')]
		except Exception:
			log(f'saveInfoToLayer error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def saveNodesToLayer(self, layer):  # SAVES NODES FROM TEMPDATA TO USERDATA.
		if layer is None or layer.name is None:
			return
		m = layer.master
		italicAngle, xHeight = m.italicAngle, m.xHeight
		bubbles = layer.tempData[TempDataBubblesKey]  # bubble tempData may not exist yet

		for side in SIDES:
			key = side.tempKey
			if isMirrored(layer, side.isLeft):
				continue  # SYNCED: THE SHAPE LIVES ON THE OTHER SIDE
			layerWidth = 0 if side.isLeft else layer.width
			value = bubbles[key] if bubbles else None
			if value:
				value = sorted(value, key=lambda node: node.y)  # SORT NODES BY HEIGHT
				# fix italic offset when transferring from tempData to userData
				userDataValue = []
				for n in value:
					userDataValue.append((int(round(tempToUserNodeX(n.x, n.y, italicAngle, xHeight) - layerWidth)), int(round(n.y))))
				# LAST GATE BEFORE USERDATA: NOTHING OFF-GRID IS EVER STORED.
				# ONLY WHEN A GRID IS SET - snap_points ALSO COLLAPSES NODES THAT
				# LAND ON ONE ROW, AND A HAND-DRAWN HORIZONTAL STEP MUST SURVIVE
				# IN A FONT WITH NO GRID.
				# A BORROWED WALL IS NOT THIS LAYER'S TO KEEP. tempData is seeded
				# with the wall a composite resolves to so the handles sit on it,
				# and writing that straight back would freeze the composite at
				# whatever its components looked like the moment somebody
				# switched glyphs. Unchanged means untouched: leave it borrowing.
				# ponytail: compared before snapping, so a merged wall that is
				# off-grid in a gridded font can still be written once.
				if not layer.userData[side.key('Nodes')]:
					# AGAINST WHAT WAS BORROWED, not against the live merge: a
					# component edited since this cache was filled would make an
					# untouched composite look edited, and the stale wall would be
					# written down. See CLAUDE.md.
					seeded = (bubbles or {}).get(TempDataBorrowedKey, {}).get(side)
					if seeded is None:
						seeded = store.nodesFromFinalBubble(layer, side.isLeft)
					if userDataValue == seeded:
						continue
				grid = store.gridFor(layer)
				if grid:
					userDataValue = store.snapStored(userDataValue, side, grid)
				layer.userData[side.key('Nodes')] = userDataValue
				recordBox(layer, side)  # THE OUTLINE THIS BUBBLE WAS DRAWN AGAINST
				# SAVE BACK TO REFLECT THE REORDERED NODES
				layer.tempData[TempDataBubblesKey][key] = value
			else:
				# A PURE COMPOSITE INHERITS ITS WALL FROM ITS COMPONENTS. The
				# default line on the origin is not a starting point for one of
				# those - it is a wall that beats everything it was meant to
				# inherit, since the merge keeps whatever reaches furthest out.
				# Leave it without one and it merges.
				if not len(layer.paths) and len(layer.components):
					continue
				if layer.shapes:
					bounds = layer.bounds
					layer.userData[side.key('Nodes')] = [(0, bounds[0][1]), (0, bounds[0][1] + bounds[1][1])]
				else:
					layer.userData[side.key('Nodes')] = [(0, m.descender), (0, m.ascender)]


	# LOAD BUBBLE FROM LAYER'S USERDATA. OPTIOINALLY LOAD TO TEMPDATA IF LAYER IS ACTIVE.
	@objc.python_method
	def loadNodesFromLayer(self, layer=None, forceLoad=False, master=None) -> dict | None:
		try:
			# shadow layer is GSLayer whose name is None: need to pass
			# need to pass line break glyph

			if not layer or isinstance(layer, GSLayer) == False:
				return None
			bubbles: dict | None = layer.tempData[TempDataBubblesKey]  # i.e. ['bubbles']
			if not forceLoad:
				if bubbles:
					prevWidth = int(bubbles['width'])
					if prevWidth != int(layer.width):
						bubbles = None
				if bubbles and bubbles.get(TempDataBorrowedKey):
					# A BORROWED WALL GOES STALE WHEN THE GLYPH IT CAME FROM MOVES,
					# AND NOTHING TELLS THIS LAYER. Compared against WHAT WAS
					# BORROWED, never against what is in tempData now: a drag has
					# changed the latter on purpose. See CLAUDE.md.
					for borrowedSide, seeded in bubbles[TempDataBorrowedKey].items():
						if seeded != store.nodesFromFinalBubble(layer, borrowedSide.isLeft):
							bubbles = None
							break
				if bubbles:
					return bubbles  # raw bubble data

			# below is when there's no tempData or when forceLoad is True.
			# In this case, we load from userData and save to tempData.

			if master is None:
				master = layer.associatedFontMaster()

			userData = layer.userData

			nodesL = userData.get("BubbleKernNodesL", None)
			nodesR = userData.get("BubbleKernNodesR", None)

			# A LAYER THAT BORROWS ITS WALL - a composite merging its components
			# - has nothing of its own to load, and the made-up default below
			# would put the handles on a line that is not the wall being drawn.
			# Take the wall it actually resolves to, so what can be grabbed is
			# what can be seen. Nothing to borrow from still falls through.
			# BORROWED FROM ANOTHER GLYPH, WHICH A MIRRORED SIDE IS NOT. A mirror
			# owns no nodes either, but what it resolves to is the OTHER SIDE OF
			# THIS LAYER, live - which is exactly what a drag is moving. Recorded
			# here it went out of date on the first pixel of every drag on the
			# other side, dropped the cache, and took the drag with it.
			borrowed = {}
			if not nodesL:
				nodesL = store.nodesFromFinalBubble(layer, True) or nodesL
				if nodesL and not isMirrored(layer, True):
					borrowed[LEFT] = nodesL
			if not nodesR:
				nodesR = store.nodesFromFinalBubble(layer, False) or nodesR
				if nodesR and not isMirrored(layer, False):
					borrowed[RIGHT] = nodesR

			# if no bubbles present, make up one and save to Temp Data (not User)
			bubbles = {}
			if borrowed:
				bubbles[TempDataBorrowedKey] = borrowed
			bounds = layer.bounds
			if not nodesL:
				if layer.shapes:
					nodesL = [(0, bounds[0][1]), (0, bounds[0][1] + bounds[1][1])]
				else:
					nodesL = [(0, master.descender), (0, master.ascender)]
					bubbles[TempDataLeftIsDefaultKey] = True
			if not nodesR:
				if layer.shapes:
					nodesR = [(0, bounds[0][1]), (0, bounds[0][1] + bounds[1][1])]
				else:
					nodesR = [(0, master.descender), (0, master.ascender)]
					bubbles[TempDataRightIsDefaultKey] = True

			bubbles[TempDataLeftNodesKey] = [makeBubbleNode(n[0], n[1], master.italicAngle, master.xHeight) for n in nodesL]
			# # nodesR'S X VALUES ARE BASED ON LAYER WIDTH WHEN SAVED
			# # IN self.bubbles TEMP DATA, THEY ARE ACTUAL VALUES
			bubbles[TempDataRightNodesKey] = [makeBubbleNode(n[0] + layer.width, n[1], master.italicAngle, master.xHeight) for n in nodesR]
			bubbles['width'] = layer.width

			layer.tempData[TempDataBubblesKey] = bubbles  # set raw bubbles in tempData

			return bubbles
		except Exception:
			log(f'loadNodesFromLayer error: {traceback.format_exc()}', error=True)
			return {}

	@objc.python_method
	def foreground(self, layer):  # layer to draw nodes
		if Glyphs.font.tool != self.__class__.__name__ or layer == None or layer.name is None:  # 'BubbleKernTool'
			return
		try:
			graphicView = self.editViewController().graphicView()
			scale = graphicView.scale()

			diameter = 7.2 / scale  # size of node
			diameter *= pow(scale, 0.1)
			radius = diameter / 2

			bubbles: dict = layer.tempData[TempDataBubblesKey]
			if bubbles is None or scale < 0.1: # no bubble or font size is smaller than 100 pts
				return

			lockedL, lockedR = store.lockedSides(layer)

			# DRAW REGULAR NODES. AN ALIGNED COMPOSITE IS EDITABLE TOO: its
			# wall is its components' merged, and the first node moved here
			# writes it down as this layer's own - which is what decomposing
			# does, arrived at by dragging rather than by asking first.
			for side, locked in zip(SIDES, (lockedL, lockedR)):
				if locked:
					continue
				color = side.color()
				for n in bubbles[side.tempKey]:
					rect = NSMakeRect(n.pos.x - radius, n.pos.y - radius, diameter, diameter)
					path = NSBezierPath.bezierPathWithOvalInRect_(rect)
					# A WASH INSIDE THE RING, so an unselected node reads as a disc
					# rather than as a hole punched in the wall behind it.
					color.colorWithAlphaComponent_(NODE_FILL_ALPHA).set()
					path.fill()
					color.set()
					path.setLineWidth_(1.2 / scale)
					path.stroke()


			# HIGHLIGHT SELECTION
			for side, locked in zip(SIDES, (lockedL, lockedR)):
				if locked:
					continue
				side.color().set()
				for n in bubbles[side.tempKey]:
					if n in layer.selection:
						rect = NSMakeRect(n.pos.x - radius, n.pos.y - radius, diameter, diameter)
						path = NSBezierPath.bezierPathWithOvalInRect_(rect)
						path.fill()

			# HIGHLIGHT NODES CLOSE TO MOUSE CURSOR

			if self.closestNode is not None:  # if mouseMoved_() says there's a add-able node on a line
				color = NSColor.systemGrayColor().colorWithAlphaComponent_(0.75)
				color.set()
				n = self.closestNode
				rect = NSMakeRect(n[0] - radius, n[1] - radius, diameter, diameter)
				path = NSBezierPath.bezierPathWithOvalInRect_(rect)
				path.setLineWidth_(1 / scale)
				path.stroke()

			self.drawPairRows(layer, scale)

		except Exception:
			log(f'foreground error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def drawPairRows(self, layer, scale):
		# THE HEIGHT AT WHICH THE BUBBLES DECIDE THIS GLYPH AGAINST EACH OF ITS
		# NEIGHBOURS. IT NAMES THE NODE THAT IS DECIDING THE PAIR, WHICH IS WHAT
		# YOU WANT TO KNOW BEFORE DRAGGING ONE.
		#
		# THE VALUE ITSELF IS NOT DRAWN. The preview writes real kerning, so
		# Glyphs already shows the number in its own place, and drawing it again
		# put two of them on the canvas disagreeing about nothing.
		try:
			font = layer.parent.parent  # NOT Glyphs.font: THAT IS AN XPC CALL PER FRAME
			if font is None:
				return
			tab = font.currentTab
			if tab is None:
				return
			index = store.tabIndexOf(tab, layer)
			if index is None:
				return
			for direction in (-1, 1):
				position = index + direction
				if position < 0:
					continue
				try:
					neighbour = tab.layers[position]
				except Exception:
					continue
				if neighbour is None or isinstance(neighbour, GSControlLayer) or neighbour.name is None:
					continue
				leftLayer, rightLayer = (layer, neighbour) if direction == 1 else (neighbour, layer)
				wallR = getFinalBubble(leftLayer, isLeft=False)
				wallL = getFinalBubble(rightLayer, isLeft=True)
				if wallR is None or wallL is None:
					continue
				value, row = getKernValue(wallR, wallL, int(leftLayer.width), withRow=True,
					space=auto.fit_space(font, leftLayer.associatedFontMaster()))
				if row is None or value == float('inf'):
					continue
				edge = layer.width if direction == 1 else 0.0

				NSColor.textColor().colorWithAlphaComponent_(0.55).set()
				tick = NSBezierPath.alloc().init()
				tick.moveToPoint_(NSPoint(edge - 8 / scale, row))
				tick.lineToPoint_(NSPoint(edge + 8 / scale, row))
				tick.setLineWidth_(1 / scale)
				tick.stroke()
		except Exception:
			log(f'drawPairRows error: {traceback.format_exc()}', error=True)

	def drawBackgroundForLayer_options_(self, layer, options):  # run drawBubbleWalls()
		'''
		options = {
			"Scale":0.12
			"Black":True/False
		}
		'''
		# log('active current tool =', Glyphs.font.tool)
		#if Glyphs.font.tool == self.__class__.__name__ and layer != None and layer.name is not None: # 'BubbleKernTool'
		# log('Drawing active layer', layer.parent)
		self.drawGrid(layer, options)
		self.drawBubbleWalls(layer, True, options)

	@objc.python_method
	def drawGrid(self, layer, drawOptions):  # SHOW WHAT THE NODES SNAP TO
		# THE ROWS THE NODES SNAP TO, AND NOTHING ELSE: a bubble node's x is a
		# measurement, and there is no line to draw for a number that is free
		# to be whatever the outline says it is.
		try:
			if layer is None or layer.name is None:
				return
			grid = store.gridFor(layer)
			if not grid:
				return
			scale = drawOptions["Scale"].doubleValue()
			if scale < 0.1:
				return
			m = layer.master
			italicAngle, xHeight = m.italicAngle, m.xHeight
			bounds = layer.bounds

			# WHERE THE BUBBLES ACTUALLY ARE, PADDED BY ONE INCREMENT
			xs, ys = [0.0, float(layer.width)], []
			if bounds.size.height > 0:
				ys += [bounds.origin.y, bounds.origin.y + bounds.size.height]
			else:
				ys += [m.descender, m.ascender]
			bubbles = layer.tempData[TempDataBubblesKey]
			if bubbles:
				for key in (TempDataLeftNodesKey, TempDataRightNodesKey):
					for node in bubbles.get(key, []):
						xs.append(node.x)
						ys.append(node.y)
			pad = grid * 2
			lowX, highX = min(xs), max(xs)
			lowY, highY = min(ys) - pad, max(ys) + pad

			# A ONE-UNIT GRID WOULD BE THOUSANDS OF LINES A FRAME. DRAW NOTHING
			# RATHER THAN CRAWL - THE NODES STILL SNAP TO IT EITHER WAY.
			maxLines = 240
			path = NSBezierPath.alloc().init()
			if (highY - lowY) / grid <= maxLines:
				y = int(math.floor(lowY / grid)) * grid
				while y <= highY:
					path.moveToPoint_(NSPoint(userToTempNodeX(lowX, y, italicAngle, xHeight), y))
					path.lineToPoint_(NSPoint(userToTempNodeX(highX, y, italicAngle, xHeight), y))
					y += grid
			if path.elementCount():
				NSColor.systemGrayColor().colorWithAlphaComponent_(0.25).set()
				path.setLineWidth_(1 / scale)
				path.stroke()
		except Exception:
			log(f'drawGrid error: {traceback.format_exc()}', error=True)

	def drawBackgroundForInactiveLayer_options_(self, layer, options):  # run drawBubbleWalls()
		if Glyphs.font.tool == self.__class__.__name__ and layer != None and layer.name is not None: # 'BubbleKernTool'
			self.drawBubbleWalls(layer, False, options)

	@objc.python_method
	def drawBubbleWalls(self, layer, active, drawOptions):  # draws the bubble
		try:
			if layer is None or layer.name is None:
				return
			# AN AUTO-ALIGNED COMPOSITE GETS ITS WALL DRAWN TOO. Editing the
			# nodes stays barred on an aligned layer; seeing the wall does not
			# need to be.
			bubbles: dict | None = self.loadNodesFromLayer(layer, False)
			scale = drawOptions["Scale"].doubleValue()
			if not bubbles or scale < 0.1: # no bubble or font size is smaller than 100 pts
				return

			for side in SIDES:
				# A MADE-UP WALL IS NOT DRAWN ON A LAYER NOBODY IS EDITING.
				if not active and bubbles.get(side.defaultKey, False):
					continue
				side.color().colorWithAlphaComponent_(0.5).set()
				if isStale(layer, side.isLeft):
					# THE OUTLINE HAS MOVED SINCE THIS WAS DRAWN.
					NSColor.systemOrangeColor().colorWithAlphaComponent_(0.7).set()
				bubblePath = getFinalBubble(layer, side.isLeft)
				if bubblePath is None:
					# THIS SIDE ONLY: a layer whose left wall resolves to nothing
					# must still draw its right one.
					continue

				if (layer.userData[side.key('Refer')] is not None
						or isMirrored(layer, side.isLeft)):  # borrowed shape: dashed
					dashPattern = [3 / scale, 3 / scale]  # draw 4pt, skip 2pt (repeat)
					bubblePath.setLineDash_count_phase_(dashPattern, len(dashPattern), 0)

				if active is True:  # WHEN IN BACKGROUND
					bubblePath.setLineWidth_(1.5 / scale)
				else:
					bubblePath.setLineWidth_(1 / scale)
				bubblePath.stroke()

		except Exception:
			log(f'drawBubbleWalls error: {traceback.format_exc()}', error=True)

	# CALLED WHEN MOUSE MOVES. CHECKS IF MOUSE IS NEAR ANY NODES OR LINE SEGMENTS TO HIGHLIGHT.
	def mouseMoved_(self, theEvent):
		objc.super(BubbleKernTool, self).mouseMoved_(theEvent)

		try:
			controller = self.editViewController()
			graphicView = controller.graphicView()
			scale = graphicView.scale()

			layer = graphicView.activeLayer()
			if layer == None or layer.name is None:
				return
			mousePos = graphicView.getActiveLocation_(theEvent)  # pos relative to active layer
			mpx, mpy = mousePos.x, mousePos.y
			clickRadiusAbsolute = clickRadius / scale  # click radius
			# highlight possible click position
			# highlight possible selectable node
			# log(layer.parent.name)
			bubbles = layer.tempData[TempDataBubblesKey]

			referL, referR = store.infoForLayer(layer)

			allNodes = []
			if not referL:
				nodesL = bubbles['nodesL']
				allNodes.extend(nodesL)
			if not referR:
				nodesR = bubbles['nodesR']
				allNodes.extend(nodesR)

			# highlight clickable node
			for n in allNodes:
				if nearNodes(n.pos, mousePos, clickRadiusAbsolute): # if mouse is near enough to a node
					if self.closestNode: # if there's one alredy
						self.closestNode = None  # for highlighting the addable node
						self.closestNodeSide = None
						controller.redraw()
					return

			# highlight possible node add position

			# two coordinate numbers, not .x and .y
			# not checking the mouse distance yet
			closestL = closestToNodes(nodesL, mousePos) if not referL else None
			closestR = closestToNodes(nodesR, mousePos) if not referR else None

			closestDeltaL = hypot(mpx - closestL[0], mpy - closestL[1]) if closestL else float('inf')
			closestDeltaR = hypot(mpx - closestR[0], mpy - closestR[1]) if closestR else float('inf')

			if closestDeltaL <= clickRadiusAbsolute:  # if L is within radius
				if closestDeltaL <= closestDeltaR:  # if L is closer than R
					closest = closestL
					self.closestNodeSide = 0
				else:  # if R is closer (R should already be True)
					closest = closestR
					self.closestNodeSide = 1
			elif closestDeltaR <= clickRadiusAbsolute:  # if R is the only one within radius
				closest = closestR
				self.closestNodeSide = 1
			else:
				closest = None
				self.closestNodeSide = None

			# if closest node is close enough to mouse cursor
			self.closestNode = closest  # for highlighting the addable node
			controller.redraw()

		except Exception:
			log(f'mouseMoved error: {traceback.format_exc()}', error=True)

	# CALLED WHEN MOUSE MOVES OR CLICKS. CHECKS IF MOUSE IS NEAR ANY NODES TO HIGHLIGHT OR SELECT.
	# THE DIFFERENCE BETWEEN THIS AND mouseMoved_() IS THAT THIS ALSO CHECKS LOCKED STATUS IF ignoreLocked IS FALSE.
	# CALLED IN elementAtPoint_() AND mouseMoved_()
	def elementAtPoint_atLayer_ignoreLocked_(self, point, layer, ignoreLocked):
		graphicView = self.editViewController().graphicView()
		scale = graphicView.scale()
		clickRadiusAbsolute = clickRadius / scale  # click radius
		# highlight possible click position
		# highlight possible selectable node
		referL, referR = store.infoForLayer(layer)

		bubbles = self.loadNodesFromLayer(layer)
		if not bubbles:
			return None

		allNodes = []
		if not referL:
			allNodes.extend(bubbles[TempDataLeftNodesKey])
		if not referR:
			allNodes.extend(bubbles[TempDataRightNodesKey])

		# highlight clickable node
		for n in allNodes:
			if nearNodes(n.pos, point, clickRadiusAbsolute):
				return n
		return None

	# CALLED AFTER DRAGGING EMPTY SPACE FOR MODIFYING SELECTION. SEEMS TO BE WORKING
	def elementsInPath_atLayer_modifier_(self, bezierPath: NSBezierPath, layer: GSLayer, modifierFlag: int):
		bubbles = self.loadNodesFromLayer(layer)
		if not bubbles:
			return None
		nodesL, nodesR = bubbles[TempDataLeftNodesKey], bubbles[TempDataRightNodesKey]
		referL, referR = store.infoForLayer(layer)

		allNodes = []
		if not referL:
			allNodes.extend(nodesL)
		if not referR:
			allNodes.extend(nodesR)

		nodes = []
		# highlight clickable node
		for n in allNodes:
			if bezierPath.containsPoint_(n.pos):
				nodes.append(n)
		return nodes

	# CALLED WHILE DRAGGING SELECTED NODES
	def moveSelectionWithPoint_withModifier_(self, offset: NSPoint, modifierFlag: int):
		if self.setActiveLayer() is False:
			return
		layer = self.activeLayer
		# ONLY OUR NODES MOVE HERE. Passing a selection that is not ours to
		# super let the outline be dragged in this tool, which is not what the
		# tool is for: it is a bubble editor, and a glyph edited by accident
		# while aiming at a wall is a worse trade than switching tools.
		if not any(isinstance(node, BubbleNode) for node in layer.selection):
			return
		bubbles = layer.tempData[TempDataBubblesKey]
		controller = self.editViewController()
		shadowLayer = controller.shadowLayer()
		shadowBubbles = self.loadNodesFromLayer(shadowLayer, master=layer.associatedFontMaster())

		if not shadowBubbles:
			return
		
		didChangeAnything = False
		lockedL, lockedR = store.lockedSides(layer)
		for side, locked in zip(SIDES, (lockedL, lockedR)):
			if locked:
				continue
			nodes = bubbles.get(side.tempKey, [])
			shadowNodes = shadowBubbles.get(side.tempKey, [])
			for node in nodes:
				# THIS IS A PROBLEM AS IDS ONLY MATCH THE FIRST TIME
				if node not in layer.selection:
					continue

				index = nodes.index(node)
				if index >= len(shadowNodes):
					# THE WALL CHANGED SHAPE SINCE THE DRAG STARTED. The snapshot
					# taken at mouseDown is what each node is dragged FROM, so it
					# has to be the same wall; a component edited underneath it, or
					# a side that resolves to a different number of nodes, and it is
					# not. tempData hands the snapshot back as an NSMutableArray,
					# which does not raise IndexError - it throws out of Python
					# altogether and Glyphs shows the alert.
					continue
				shadowNode = shadowNodes[index]
				pos = shadowNode.pos
				pos = addPoints(pos, offset)
				node.pos = NSPoint(round(pos.x), round(pos.y))
				if modifierFlag & NSEventModifierFlagShift:  # ⇧ LINES IT UP
					self.alignNode(node, nodes, index, layer.selection)
				if not (modifierFlag & NSEventModifierFlagOption):  # ⌥ BYPASSES THE GRID
					store.snapNode(node, layer, not side.isLeft)
				didChangeAnything = True

		if didChangeAnything:
			# THE WALL MOVED, SO THE KERNING IT IMPLIES MOVED WITH IT.
			# `getFinalBubble` reads tempData, which is where the node being
			# held lives, so this measures the wall under the cursor rather
			# than the one last written to userData.
			#
			# COALESCED, because this runs on every delta of the drag and a
			# full apply is the whole tab's kerning taken out and put back.
			# The redraw stays here so the node keeps up with the cursor; the
			# figures catch up a turn of the run loop later.
			self.previewKerningSoon()
			Glyphs.redraw()

	@objc.python_method
	def selectedBubbleNode(self, layer):
		"""The one bubble node selected, and its side. -> (node, isRight)

		One, not some: two nodes selected have two sets of coordinates and the
		strip has room to be honest about neither.
		"""
		try:
			bubbles = layer.tempData[TempDataBubblesKey] if layer is not None else None
			if not bubbles:
				return None, False
			selection = layer.selection or []
			found = [(node, not side.isLeft)
				for side in SIDES
				for node in (bubbles.get(side.tempKey) or [])
				if node in selection]
			return found[0] if len(found) == 1 else (None, False)
		except Exception:
			log(f'selectedBubbleNode error: {traceback.format_exc()}', error=True)
			return None, False

	@objc.python_method
	def storedCoordinates(self, layer, node, isRight):
		"""A node's position as the file writes it down. -> (x, y)

		The same two numbers the card on the canvas shows: upright, and a right
		wall measured back from its own advance.
		"""
		m = layer.master
		x = tempToUserNodeX(node.x, node.y, m.italicAngle, m.xHeight)
		return (x - layer.width if isRight else x), node.y

	@objc.python_method
	def moveBubbleNodeTo(self, layer, node, isRight, x, y):
		"""Put a node where the strip says it should be. -> True if it moved

		Undo, snapping and the write-back are the drag's, so a number typed here
		and a node dragged there end up as the same edit.
		"""
		try:
			m = layer.master
			if isRight:
				x = x + layer.width
			where = NSPoint(round(userToTempNodeX(x, y, m.italicAngle, m.xHeight)),
				round(y))
			if (round(node.x), round(node.y)) == (where.x, where.y):
				return False
			layer.parent.beginUndo()
			try:
				node.pos = where
				store.snapNode(node, layer, isRight)
				# saveNodesToLayer SORTS BY HEIGHT on the way out, so a node
				# typed past its neighbour lands in the right place in the wall.
				self.saveNodesToLayer(layer)
			finally:
				layer.parent.endUndo()
			return True
		except Exception:
			log(f'moveBubbleNodeTo error: {traceback.format_exc()}', error=True)
			return False

	@objc.python_method
	def showCoordinates(self, layer):
		"""Fill the strip in, or take it away. -> None"""
		try:
			view = getattr(self, 'coordsView', None)
			if view is None:
				return
			node, isRight = self.selectedBubbleNode(layer)
			if node is None:
				view.setHidden_(True)
				return
			x, y = self.storedCoordinates(layer, node, isRight)
			self.w.coords.x.set(str(int(round(x))))
			self.w.coords.y.set(str(int(round(y))))
			view.setHidden_(False)
			view.setNeedsDisplay_(True)
		except Exception:
			log(f'showCoordinates error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def coordEdited(self, sender=None):
		try:
			if self.setActiveLayer() is False:
				return
			layer = self.activeLayer
			node, isRight = self.selectedBubbleNode(layer)
			if node is None:
				return
			was = self.storedCoordinates(layer, node, isRight)
			x = auto._number(str(self.w.coords.x.get()).strip(), was[0])
			y = auto._number(str(self.w.coords.y.get()).strip(), was[1])
			if self.moveBubbleNodeTo(layer, node, isRight, x, y):
				store.applyPreviewKerning()
			self.showCoordinates(layer)
			Glyphs.redraw()
		except Exception:
			log(f'coordEdited error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def keepOnlyBubbleNodes(self, layer):
		"""Nothing but this tool's own nodes stays selected. -> None

		The outline is not this tool's to touch, but SelectTool finds a segment
		under the cursor by its own means and selects it even though
		`elementAtPoint:` answered None. Nothing here would move it, but the
		app's own handlers are happy to act on it. See CLAUDE.md.
		"""
		try:
			if layer is None:
				return
			selection = list(layer.selection or [])
			kept = [item for item in selection if isinstance(item, BubbleNode)]
			if len(kept) != len(selection):
				layer.selection = kept
		except Exception:
			log(f'keepOnlyBubbleNodes error: {traceback.format_exc()}', error=True)

	def mouseUp_(self, theEvent):
		try:
			objc.super(BubbleKernTool, self).mouseUp_(theEvent)  # Let Glyphs do its default mouseUp_
			self.setActiveLayer()
			self.keepOnlyBubbleNodes(self.activeLayer)
			self.saveNodesToLayer(self.activeLayer)
			self.loadNodesFromLayer(self.activeLayer)
			store.applyPreviewKerning()  # THE WALL MOVED, SO THE PREVIEW SHOULD
			Glyphs.redraw()
		except Exception:
			log(f'mouseUp_ error: {traceback.format_exc()}', error=True)

	def mouseDown_(self, theEvent):
		try:
			# if the click is a double click, let Glyphs handle it (e.g. for text editing)
			if theEvent.clickCount() > 1:
				objc.super(BubbleKernTool, self).mouseDown_(theEvent)
				return

			controller = self.editViewController()
			graphicView = controller.graphicView()

			if layer := graphicView.activeLayer():
				m = layer.associatedFontMaster()
				scale = graphicView.scale()
				clickPosition = graphicView.getActiveLocation_(theEvent)
				cpx, cpy = clickPosition.x, clickPosition.y

				clickRadiusAbsolute = clickRadius / scale  # click radius
				bubbles = layer.tempData[TempDataBubblesKey]
				nodesL, nodesR = bubbles[TempDataLeftNodesKey], bubbles[TempDataRightNodesKey]
				allNodes = nodesL + nodesR

				hit_index = None # index of the node that is near the click position, if any
				for i, node in enumerate(allNodes):  # find the possibly selected node. Escape as soon as it finds one
					if nearNodes(node.pos, clickPosition, clickRadiusAbsolute):
						hit_index = i
						break

				if hit_index is None and self.closestNode:  # NO EXISTING NODE CLICKED, BUT THERE'S A POSSIBLE ADD POSITION
					nodeAdded = False # STARTING VALUE
					# nodeAdded REMAINS FALSE WHEN NEITHER IS SELECTABLE, I.E. CLICK IS TOO FAR FROM BOTH BUBBLES

					# GET THE THEORETICAL CLOSEST POINT(S) TO THE CLICKED POSITION
					closestL = closestToNodes(nodesL, clickPosition)  # TWO COORDINATE NUMBERS, NOT .X AND .Y
					closestR = closestToNodes(nodesR, clickPosition)
					if closestL is None or closestR is None:
						return
					# EVALUATE WHICH BUBBLE IS WITHIN CLICKED POSITION AND WHICH IS CLOSER
					closestDeltaL = hypot(cpx - closestL[0], cpy - closestL[1])
					closestDeltaR = hypot(cpx - closestR[0], cpy - closestR[1])
					if closestDeltaL <= clickRadiusAbsolute:  # IF closestL IS SELECTABLE
						if closestDeltaL <= closestDeltaR:  # nodesL IS CLOSER, R MAY BE IN OR OUT
							nodes = nodesL
							closest = closestL
							sideName = TempDataLeftNodesKey
							nodeAdded = True
						else:  # R IS MORE SELECTABLE (WHEN BOTH SHOULD BE SELECTABLE)
							nodes = nodesR
							closest = closestR
							sideName = TempDataRightNodesKey
							nodeAdded = True
					elif closestDeltaR <= clickRadiusAbsolute:  # IF ONLY closestR IS SELECTABLE
						nodes = nodesR
						closest = closestR
						sideName = TempDataRightNodesKey
						nodeAdded = True
					
					# CHECK IF THE CLOSEST NODE IS WITHIN CLICKABLE RADIUS
					# IF CLOSE ENOUGH, THAT'S A NEW NODE
					if nodeAdded is True:
						layer.parent.beginUndo()  # for undo grouping
						newX = tempToUserNodeX(closest[0], closest[1], m.italicAngle, m.xHeight)  # correct for italic angle
						new_node = makeBubbleNode(newX, closest[1], m.italicAngle, m.xHeight)
						store.snapNode(new_node, layer, sideName is TempDataRightNodesKey)

						# INSERT AT CORRECT POS, NOT AT THE LAST INDEX
						nodes.append(new_node)

						bubbles[sideName] = sorted(nodes, key=lambda n: n.pos.y)
						self.saveNodesToLayer(layer)
						layer.parent.endUndo()  # end undo grouping

						layer.selection = [new_node]
						controller.redraw()
						return
			objc.super(BubbleKernTool, self).mouseDown_(theEvent)
			self.keepOnlyBubbleNodes(graphicView.activeLayer())

		except Exception:
			log(f'mouseDown_ error: {traceback.format_exc()}', error=True)

	def keyDown_(self, theEvent):
		"""Typing adds glyphs to the tab, the way the Text tool does.

		`insertText:` on the tab does the insertion, cursor and all.

		PLAIN TYPING ONLY. Anything held down makes it a shortcut - and SPACE is
		left alone on purpose, because it pans the canvas here.
		"""
		try:
			characters = theEvent.charactersIgnoringModifiers()
			held = theEvent.modifierFlags() & (NSEventModifierFlagCommand
				| NSEventModifierFlagOption | NSEventModifierFlagControl)
			if characters and not held and all(
					character.isprintable() and character != ' '
					for character in characters):
				font = Glyphs.font
				tab = font.currentTab if font is not None else None
				if tab is not None:
					tab.insertText_(characters)
					return
		except Exception:
			log(f'keyDown_ error: {traceback.format_exc()}', error=True)
		objc.super(BubbleKernTool, self).keyDown_(theEvent)

	def addMenuItemsForEvent_toMenu_(self, theEvent, contextMenu):
		"""Put the settings on the canvas's own right-click menu.

		They left the two side menus when those became per-side commands, and a
		panel that shapes every wall in the font did not belong under a button
		that draws one of them.
		"""
		try:
			# NEAR THE FOOT, where the tool template puts a tool's own commands:
			# inserting at the top would push every item Glyphs put there down and
			# move things people reach for without looking.
			where = max(0, contextMenu.numberOfItems() - 1)
			contextMenu.insertItem_atIndex_(NSMenuItem.separatorItem(), where)
			where += 1
			# DECOMPOSE ONLY WHERE THERE IS SOMETHING TO DECOMPOSE - a side that
			# borrowed its shape. On a side drawn from its own nodes the command
			# would replace them with a copy of themselves.
			layer = self.activeLayer if self.setActiveLayer() else None
			if layer is not None:
				for borrowed, title, action in zip(
					store.lockedSides(layer),
					('Decompose Left Bubble', 'Decompose Right Bubble'),
					('decomposeLeft:', 'decomposeRight:')):
					if not borrowed:
						continue
					entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
						title, action, '')
					entry.setTarget_(self)
					contextMenu.insertItem_atIndex_(entry, where)
					where += 1
			item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
				'BubbleKern Settings…', 'openSettings:', '')
			item.setTarget_(self)
			contextMenu.insertItem_atIndex_(item, where)
		except Exception:
			log(f'addMenuItemsForEvent_toMenu_ error: {traceback.format_exc()}',
				error=True)

	def decomposeLeft_(self, sender):
		NSOperationQueue.mainQueue().addOperationWithBlock_(
			lambda: self.decomposeBubble(True))

	def decomposeRight_(self, sender):
		NSOperationQueue.mainQueue().addOperationWithBlock_(
			lambda: self.decomposeBubble(False))

	def insertTab_(self, sender):  # WHEN TAB IS PRESSED
		self._selectNext(1)

	def insertBacktab_(self, sender):  # WHEN SHIFT+TAB IS PRESSED
		self._selectNext(-1)

	@objc.python_method
	def _selectNext(self, direction):  # CYCLE THROUGH SELECTED NODE WITH TAB
		try:
			layer = self.activeLayer
			bubbles = layer.tempData[TempDataBubblesKey]
			allNodes = bubbles.get(TempDataLeftNodesKey, []) + bubbles.get(TempDataRightNodesKey, [])

			selection = [n for n in layer.selection if isinstance(n, BubbleNode)]
			if len(selection) == 0:
				return
			index = allNodes.index(selection[0])
			nextNode = allNodes[(index + direction) % len(allNodes)]
			layer.selection = [nextNode]
		except Exception:
			log(f'_selectNext error: {traceback.format_exc()}', error=True)


	# CALLED WHEN SELECT ALL HAS BEEN CALLED FROM THE APP
	def selectAll_(self, sender):
		# EVERY NODE THIS TOOL COULD ACTUALLY MOVE. `lockedSides` is the same
		# answer the drag and the drawing already use, so a side that borrows
		# its shape is left out of the selection by the one test.
		try:
			layer = self.editViewController().activeLayer()
			bubbles = layer.tempData[TempDataBubblesKey]
			nodesToAdd = []
			for locked, key in zip(store.lockedSides(layer),
					(TempDataLeftNodesKey, TempDataRightNodesKey)):
				for node in bubbles.get(key, []):
					node.selected = False
					if not locked:
						nodesToAdd.append(node)
			layer.selection = nodesToAdd
			Glyphs.redraw()
		except Exception:
			log(f'selectAll_ error: {traceback.format_exc()}', error=True)

	def alignPoints_(self, sender):
		alignment = Glyphs.defaults["GSTransformGridCorner"]
		# GSTopLeft = 6,
		# GSTopCenter = 7,
		# GSTopRight = 8,
		# GSCenterLeft = 3,
		# GSCenterCenter = 4,
		# GSCenterRight = 5,
		# GSBottomLeft = 0,
		# GSBottomCenter = 1,
		# GSBottomRight = 2,
		layer = self.activeLayer
		# get selection size

		bubbles = layer.tempData[TempDataBubblesKey]

		allNodes = bubbles.get(TempDataLeftNodesKey, []) + bubbles.get(TempDataRightNodesKey, [])

		selectedNodes = [n for n in allNodes if n in layer.selection]

		if len(selectedNodes) > 1:  # if there are 2 or more nodes selected

			xCoords = [n.pos.x for n in selectedNodes]
			xMin, xMax = min(xCoords), max(xCoords)

			yCoords = [n.pos.y for n in selectedNodes]
			yMin, yMax = min(yCoords), max(yCoords)

			if xMax - xMin < yMax - yMin:  # TALLER SELECTION BOX; FLATTEN X VALUES
				if alignment in (0, 3, 6):   # X MININUM
					alignX = int(round(xMin))
				elif alignment in (1, 4, 7):  # X CENTRE
					alignX = int(round(xMin + (xMax - xMin) / 2))
				else:                      # X MAX
					alignX = int(round(xMax))
				for n in selectedNodes:
					n.pos = NSPoint(alignX, n.pos.y)
			else:                     # WIDER SELECTION BOX; FLATTEN Y VALUES
				# THE BOTTOM ROW IS 0, 1 AND 2.
				if alignment in (0, 1, 2):   # Y MINIMUM
					alignY = int(round(yMin))
				elif alignment in (3, 4, 5):  # Y CENTRE
					alignY = int(round(yMin + (yMax - yMin) / 2))
				else:                      # Y MAX
					alignY = int(round(yMax))
				for n in selectedNodes:
					n.pos = NSPoint(n.pos.x, alignY)
			self.saveNodesToLayer(layer)
			Glyphs.redraw()

	def delSelectionWithModifier_(self, modifierFlag):  # Called when Delete is pressed
		controller = self.editViewController()
		layer = self.activeLayer
		if layer and layer.selection:
			bubbles = layer.tempData[TempDataBubblesKey]
			if not bubbles:
				return
			for selection in layer.selection:
				nodeL = bubbles[TempDataLeftNodesKey]
				nodeR = bubbles[TempDataRightNodesKey]
				if selection in nodeL:
					nodeL.remove(selection)
				if selection in nodeR:
					nodeR.remove(selection)

			# If a side is now empty, restore it to the default bubble
			for side in SIDES:
				if not bubbles[side.tempKey]:
					self.resetBubble(side.isLeft, layer=layer)
					return  # resetBubble already calls saveNodesToLayer and redraw

			self.saveNodesToLayer(layer)
			controller.redraw()

	@objc.python_method
	def resetBubble(self, isLeft, layer=None):  # RESETS ONE SIDE TO DEFAULT BUBBLE ALIGNED TO LAYER BOUNDS
		if layer is None:
			if self.setActiveLayer() is False:
				return
			layer = self.activeLayer
		bubbles = layer.tempData.get(TempDataBubblesKey)
		if bubbles is None:
			return
		m = layer.master
		key = TempDataLeftNodesKey if isLeft else TempDataRightNodesKey
		layerWidth = 0 if isLeft else layer.width
		if layer.shapes:
			bounds = layer.bounds
			defaultNodes = [(layerWidth, bounds[0][1]), (layerWidth, bounds[0][1] + bounds[1][1])]
		else:
			defaultNodes = [(layerWidth, m.descender), (layerWidth, m.ascender)]
		bubbles[key] = [makeBubbleNode(x, y, m.italicAngle, m.xHeight) for x, y in defaultNodes]
		self.saveNodesToLayer(layer)
		Glyphs.redraw()

	# FIRES AFTER NSUndoManager FINISHES AN UNDO
	# ALWAYS FORCE-RELOADS TEMPDATA FROM USERDATA (WHICH GLYPHS HAS AUTO-RESTORED) AND REDRAWS,
	# SO THAT BOTH COUNT CHANGES (DELETE) AND POSITION CHANGES (MOVE) ARE HANDLED.
	def _undoDidComplete_(self, notification):
		if self.setActiveLayer() is False:
			return
		layer = self.activeLayer
		bubbles = layer.tempData.get(TempDataBubblesKey)
		if not bubbles:
			return
		self.loadNodesFromLayer(layer, forceLoad=True)
		Glyphs.redraw()

	@objc.python_method
	def decomposeBubble(self, isLeft):  # CALLED FROM INFO BOX; decompose referenced bubble & remove reference
		try:
			if self.setActiveLayer() is False:
				return
			self.activeLayer.parent.beginUndo()  # begin undo for the whole operation

			# need to check if the bubble is from a reference or not, because if it's from a reference, we need to get the bubble path from the referred layer instead of the active layer
			# or the menu item should be disabled in the first place

			m = self.activeLayer.master
			bubblePath = getFinalBubble(self.activeLayer, isLeft)

			width = self.activeLayer.width if isLeft == False else 0
			bubbleDataTemp = []
			for i in range(bubblePath.elementCount()):
				element = bubblePath.elementAtIndex_associatedPoints_(i) # tuple of node type and node(s)
				n = element[1][0]
				bubbleDataTemp.append(((round(tempToUserNodeX(n.x - width, n.y, m.italicAngle, m.xHeight))), int(round(n.y))))

			# save nodes to userData
			side = of(isLeft)
			key = side.key('Nodes')
			self.activeLayer.userData[key] = bubbleDataTemp

			# remove whatever the side was borrowing from
			referKey = side.key('Refer')
			del self.activeLayer.userData[referKey]
			mirrorKey = side.key('Mirror')
			if self.activeLayer.userData[mirrorKey]:
				del self.activeLayer.userData[mirrorKey]
			self.updateUI() # need to force reloading since the context menu has already been generated with the old reference state

			self.loadNodesFromLayer(self.activeLayer, forceLoad=True)  # reload tempData from userData to reflect the decomposed bubble

			self.activeLayer.parent.endUndo()  # end undo
			Glyphs.redraw()
		except Exception:
			log(f'decomposeBubble error: {traceback.format_exc()}', error=True)

	# AUTOMATIC BUBBLES AND THE GRID. THE MEASUREMENT LIVES IN BKAutoBubble;
	# EVERYTHING HERE IS ABOUT GETTING IT ONTO GLYPHS AND BACK.

	@objc.python_method
	def magnetReach(self):  # HOW CLOSE COUNTS AS CLOSE, IN FONT UNITS
		# A FIXED NUMBER OF SCREEN POINTS, not of font units: magnetism is
		# about what the hand can hold still, and a hand at 400% zoom can hold
		# a great deal stiller than the same hand at 20%.
		try:
			scale = float(self.editViewController().graphicView().scale())
		except Exception:
			scale = 1.0
		return max(1.0, MAGNET_POINTS / max(0.01, scale))

	@objc.python_method
	def alignNode(self, node, nodes, index, selection):
		"""Pull a dragged node onto a neighbour's line, if it is nearly there.

		BOTH WAYS, and each on its own. A wall is read bottom to top, so an
		upright piece of one is two nodes at the same x and a flat piece is two
		at the same y; either is worth finishing off. The two axes are decided
		separately, so a node can take its x from the neighbour below and its y
		from the one above and land on the corner they make.

		A neighbour being dragged in the same gesture is no anchor - it is
		moving too, and lining up with a moving target would be lining up with
		nothing.
		"""
		try:
			reach = self.magnetReach()
			nearX = nearY = reach
			foundX = foundY = None
			for offset in (-1, 1):
				position = index + offset
				if position < 0 or position >= len(nodes):
					continue
				other = nodes[position]
				if other in selection:
					continue
				gap = abs(other.pos.x - node.pos.x)
				if gap <= nearX:
					nearX, foundX = gap, other.pos.x
				gap = abs(other.pos.y - node.pos.y)
				if gap <= nearY:
					nearY, foundY = gap, other.pos.y
			if foundX is not None or foundY is not None:
				# ONLY THE AXIS THAT FOUND SOMETHING MOVES. The other one is
				# still the hand's answer, and rounding it here would be a
				# second, uninvited opinion about it.
				node.pos = NSPoint(round(foundX) if foundX is not None else node.pos.x,
					round(foundY) if foundY is not None else node.pos.y)
		except Exception:
			log(f'alignNode error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def refreshAfterWrite(self):
		"""Take up what a run just wrote: reload the cache and redraw. -> None

		These four lines stood at the end of `autoGenerate`, `syncBubble` and
		`applyAutoGroup` - the three things that write bubbles and then want the
		canvas to agree with the file.
		"""
		try:
			if self.setActiveLayer():
				self.loadNodesFromLayer(self.activeLayer, forceLoad=True)
				self.updateUI()
			Glyphs.redraw()
		except Exception:
			log(f'refreshAfterWrite error: {traceback.format_exc()}', error=True)

	# --- PREVIEWING THE BUBBLE KERNING IN THE BOTTOM BAR ---
	# THE PREVIEW LAYS ITS TEXT OUT FROM font.kerning, SO NOTHING DRAWN CAN MOVE
	# THOSE GLYPHS: TO SEE BUBBLE KERNING DOWN THERE THE VALUES HAVE TO EXIST.
	# THEY ARE WRITTEN ONLY WHERE THE PAIR HAS NONE - OTHERWISE THE PREVIEW WOULD
	# SHOW THE FONT'S OWN KERNING AND THIS ON TOP OF IT - AND EVERY PAIR WRITTEN
	# IS RECORDED IN font.userData, WHICH SURVIVES A SAVE. THAT RECORD IS THE
	# WHOLE SAFETY OF THE FEATURE: THERE IS NO WILL-SAVE CALLBACK IN GLYPHS, SO
	# A ⌘S WHILE THE PREVIEW IS ON DOES BAKE THESE IN, AND THE RECORD IS WHAT
	# LETS THE NEXT ACTIVATION TAKE THEM BACK OUT AGAIN.


	# --- FITTING THE SETTINGS TO KERNING DONE BY HAND ---

	# --- SETTINGS WINDOW ---

	# --- WHICH PAIRS TO MATCH ---

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
