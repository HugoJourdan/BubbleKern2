# encoding: utf-8
"""A shared badge for plugins that take over the preview panel.

Glyphs' preview panel shows the text you typed. A reporter can take it over —
`drawPreviewInLayer:` plus `needsExtraMainOutlineDrawingInPreviewLayer:` to
suppress Glyphs' own drawing — and then the panel is showing something that
nothing on screen accounts for. This is the something: a row of page dots in
the edit tab's bottom toolbar, one for Glyphs' own preview and one for each
plugin offering another, with the one showing filled in. Clicking a dot hands
the panel to it. Nothing is written on the row — so the dots never move as they
are clicked through — but switching puts the new mode's name up over the bottom
of the preview for a couple of seconds, and there is a tooltip on each dot for
the rest of the time. It slides up out of the
bottom of the toolbar whenever the preview panel is open, and back down out of
sight when it is shut.

There is no such thing in Glyphs to build on. The application has hooks for
drawing a preview and no notion of who is drawing it, so several plugins can
each quietly take the panel with no way for anyone — the user included — to see
which of them won. That is what this is for, and why it is shared rather than
copied: **one row per tab, with a dot for every plugin that offers a preview**,
not one row per plugin. Two switches side by side would be nonsense.

Adopting it, in full:

    import previewbadge

    previewbadge.register(
        identifier="com.example.MyPlugin",   # yours, and stable
        name="My Preview",                   # what your dot's tooltip says
        isActive=lambda: self.inPreview(),
        activate=lambda: self.setPreview(True),
        deactivate=lambda: self.setPreview(False),
    )

and, when your plugin is switched off:

    previewbadge.unregister("com.example.MyPlugin")

Everything else — finding tabs as they open, putting the badge in, taking it
out, sliding it in and out of sight, and the switching itself — is this
module's job. `refresh()` is there for when you change your own state
behind its back, from a menu item of your own.

There is an entry in View → Navigation as well — "Next Preview Mode" — which
steps through the same modes the dots do. It is there to be given a keyboard
shortcut, in Glyphs' settings under Shortcuts, and it belongs to the row
rather than to any one plugin: one entry, however many plugins are offering a
preview, put up with the first of them and taken down with the last.

**Copy this file into your plugin's Resources folder.** It is written to be
copied: several plugins will each have their own copy, loaded separately, and
they have to add up to one row of dots. Two things make that work.

The registry lives in `sys.modules` under a reserved name, which is process
wide, so every copy finds the same one whatever module name it was loaded
under. And the views are built by a class that the registry holds rather than
one each copy defines, because defining an Objective-C class a second time
under the same name does not shadow the first — it raises. First copy loaded
builds the class; the rest borrow it. So the newest copy installed does not
necessarily provide the drawing, and the contract below is what keeps that
from mattering: it is data, plain lists and dicts, and it does not change
shape without the number changing with it.
"""

import sys
import time
import types

from AppKit import (
	NSBezierPath,
	NSColor,
	NSFont,
	NSFontAttributeName,
	NSForegroundColorAttributeName,
	NSMakeRect,
	NSMakeSize,
	NSMenuItem,
	NSObject,
	NSView,
)
from Foundation import (
	NSAttributedString,
	NSNotificationCenter,
	NSRunLoop,
	NSRunLoopCommonModes,
	NSTimer,
)

# ------------------------------------------------------------- the look of it

DEFAULT_NAME = "Default"
# One dot per mode, the one showing filled and the rest left open. Page dots,
# and nothing else: no name, so the row is the same width whatever is showing
# and the dots stay where they are as they are clicked through.
DOT = 8.208
DOT_GAP = 5.4
RING = 1.8
# The row is flush with the bottom of the strip, so its own middle sits low in
# a 30pt bar. A point up puts the dots nearer the middle of what they are on,
# which is what the eye measures them against.
DOT_RISE = 1.0
# Room either side, so the outer dots are not on the very edge of what can be
# clicked.
SIDE = 5.0
# As tall as the badge always was — a comfortable target in a 30pt strip, and
# the distance the row slides in and out.
HEIGHT = 22.0

# Switching says what it switched to, above the dots, and then gets out of the
# way. Long enough to read a short name, and gone before it is in the way.
HOLD = 1.5
FADE = 0.3
NAME_SIZE = 12.0
NAME_PAD = (8.0, 3.5)
NAME_RADIUS = 5.0
# Flush with the bottom edge of the panel: as low as the name goes without
# leaving it. It is over somebody's type, and the bottom of the panel is the
# emptiest part of it — and sitting on the edge, it reads as belonging to the
# toolbar under it, which is where the dots it is naming are.
NAME_ABOVE = 0.0
# Below this the panel is shut, not merely small. Glyphs answers 0 for a shut
# one, but a couple of points of a panel is not a panel either.
PANEL_MIN_HEIGHT = 16.0
# Fast enough to feel immediate when the panel is opened or shut, and cheap:
# a tick that finds nothing changed does nothing.
TICK = 0.25
# How long the badge takes to slide in or out of the strip. Short: this is a
# reveal, not a transition, and anything slower reads as lag on the panel.
SLIDE = 0.18
# And how often it is moved along while it slides.
FRAME = 1.0 / 60.0

# ------------------------------------------------------- the shared registry

# Reserved: a real module of this name would be a surprising thing to find.
SHARED_KEY = "GlyphsPreviewBadgeShared"
# The shape of what lives under that key. Copies of this file that agree on
# this number agree on the contents; a copy finding a higher one leaves it
# alone and works with it, so an older plugin cannot drag a newer badge back.
# 2: the View menu entry, which the registry holds for the same reason it holds
# the badges — there is one of it for all the plugins there are.
CONTRACT = 2


def shared():
	"""The one registry, wherever it was first put there from."""
	store = sys.modules.get(SHARED_KEY)
	if store is None:
		store = types.ModuleType(SHARED_KEY)
		store.contract = CONTRACT
		store.providers = []   # [{id, name, isActive, activate, deactivate}]
		store.badges = []      # the badge views, one per tab that has one
		store.badgeClass = None
		store.nameClass = None
		store.wardenClass = None
		store.warden = None
		store.timer = None
		store.frameTimer = None
		store.told = None
		store.menuItem = None
		sys.modules[SHARED_KEY] = store
	elif getattr(store, "contract", 0) < CONTRACT:
		# An older copy got here first. The lists are the contract, so they
		# carry over; anything this version expects and that one did not is
		# filled in here.
		store.contract = CONTRACT
		for name, empty in (("providers", list), ("badges", list)):
			if not hasattr(store, name):
				setattr(store, name, empty())
		for name in ("badgeClass", "nameClass", "wardenClass", "warden",
		             "timer", "frameTimer", "told", "menuItem"):
			if not hasattr(store, name):
				setattr(store, name, None)
	return store


# ------------------------------------------------------------- what it says

def providerNames():
	"""Every mode the arrows step through, Glyphs' own preview first."""
	return [DEFAULT_NAME] + [p["name"] for p in shared().providers]


def currentIndex():
	"""Which of those is showing. 0 is Glyphs' own preview.

	The first plugin that says it has the panel, because only one of them can
	be drawing in it — and if two disagree, the badge should say something
	rather than nothing.
	"""
	for index, provider in enumerate(shared().providers):
		try:
			if provider["isActive"]():
				return index + 1
		except Exception:
			pass
	return 0


def currentName():
	names = providerNames()
	index = currentIndex()
	return names[index] if index < len(names) else DEFAULT_NAME


def show(index):
	"""Give the panel to one mode, and take it off every other.

	Taken off first, so that two plugins are never both drawing in the panel
	partway through the change.
	"""
	providers = shared().providers
	wanted = providers[index - 1] if index > 0 else None
	for provider in providers:
		if provider is wanted:
			continue
		try:
			if provider["isActive"]():
				provider["deactivate"]()
		except Exception:
			pass
	if wanted is not None:
		try:
			if not wanted["isActive"]():
				wanted["activate"]()
		except Exception:
			pass
	refresh()


def nextIndex():
	"""The mode a step forward lands on, and round to the first after the last.

	None when there is nowhere to step to, which is the rule the dots follow by
	not being drawn at all: one mode is not something to switch between.
	"""
	count = modeCount()
	if count < 2:
		return None
	return (currentIndex() + 1) % count


def stepMode():
	"""Hand the panel to the next mode along. Answers whether it moved.

	The modes in the order the dots are in, so that the menu entry and the row
	are the one switch: what the shortcut does is what clicking the next dot
	along does, and with two modes — which is the usual number — it is a toggle.
	"""
	index = nextIndex()
	if index is None:
		return False
	show(index)
	return True


# ------------------------------------------------------------ how it is drawn

def firstColour(names):
	"""The first of these NSColor class methods this macOS answers to."""
	for name in names:
		getter = getattr(NSColor, name, None)
		if getter is None:
			continue
		try:
			colour = getter()
		except Exception:
			continue
		if colour is not None:
			return colour
	return None


def quietColour():
	"""What the toolbar draws its own controls in: white on a dark one, black
	on a light one. The dots are the toolbar's, not a plugin's, so they are
	drawn in its colour and not in an accent."""
	return firstColour(("labelColor", "controlTextColor", "textColor")) \
		or NSColor.textColor()


def modeCount():
	return len(providerNames())


def dotsWidth():
	"""How wide the row of dots is.

	Nothing at all while there is only one mode: a switch between one thing
	and itself is not a switch, and a single dot would be a button that does
	nothing.
	"""
	count = modeCount()
	if count < 2:
		return 0.0
	return count * DOT + (count - 1) * DOT_GAP


def badgeSize():
	"""How much room the row takes.

	Nothing here depends on which mode is showing, so the dots stay exactly
	where they are as they are clicked through: a control that moves out from
	under the pointer as you use it is not one you can use twice.
	"""
	return (dotsWidth() + 2.0 * SIDE, HEIGHT)


def dotsLeft(bounds):
	"""Where the row begins: the middle of whatever room it was given."""
	return bounds.origin.x + (bounds.size.width - dotsWidth()) / 2.0


def dotCentre(bounds, index):
	return dotsLeft(bounds) + index * (DOT + DOT_GAP) + DOT / 2.0


def dotRect(bounds, index, inset=0.0):
	middleY = bounds.origin.y + bounds.size.height / 2.0 + DOT_RISE
	centre = dotCentre(bounds, index)
	return NSMakeRect(
		centre - DOT / 2.0 + inset, middleY - DOT / 2.0 + inset,
		DOT - 2.0 * inset, DOT - 2.0 * inset)


def dotAt(bounds, x):
	"""Which dot a point is on, or None if it is not on the row at all.

	The whole width belongs to the dots: half the gap either side of each, and
	the room at the ends to the outer two. A dot is 8pt across, and the point
	of a target that small is that its share of the control is bigger than it
	is.
	"""
	if dotsWidth() <= 0.0:
		return None
	if x < bounds.origin.x or x > bounds.origin.x + bounds.size.width:
		return None
	index = int((x - dotsLeft(bounds) + DOT_GAP / 2.0) // (DOT + DOT_GAP))
	return min(max(index, 0), modeCount() - 1)


def tipAt(bounds, x):
	"""The name of the mode whose dot is at a point.

	Nothing is written on the row, so this is the only thing that says what a
	dot will do before it is clicked.
	"""
	index = dotAt(bounds, x)
	names = providerNames()
	if index is None or index >= len(names):
		return None
	return names[index]


def drawBadge(view):
	"""A dot for each mode: the one showing filled, the rest left open.

	The one arrangement of dots that everybody reads without being told. All in
	the toolbar's own colour rather than an accent — this is a control on a
	toolbar, and it should look like the rest of what is on there.
	"""
	bounds = view.bounds()
	if dotsWidth() <= 0.0:
		return
	pressed = getattr(view, "pressed", None)
	current = currentIndex()
	for index in range(modeCount()):
		filled = index == current
		colour = quietColour()
		alpha = 1.0 if filled else 0.32
		if pressed == index:
			alpha *= 0.45
		if alpha < 1.0:
			colour = colour.colorWithAlphaComponent_(alpha)
		colour.set()
		if filled:
			NSBezierPath.bezierPathWithOvalInRect_(dotRect(bounds, index)).fill()
		else:
			# Stroked down the middle of the line, so an open dot ends up the
			# same size on the outside as a filled one.
			ring = NSBezierPath.bezierPathWithOvalInRect_(
				dotRect(bounds, index, RING / 2.0))
			ring.setLineWidth_(RING)
			ring.stroke()


def nameOpacity(elapsed):
	"""How solid the name is, that many seconds after it went up.

	Whole for HOLD, then away over FADE. Linear: it is a fade, and the point of
	it is to stop being read, not to be watched.
	"""
	if elapsed < 0.0:
		return 0.0
	if elapsed < HOLD:
		return 1.0
	if elapsed >= HOLD + FADE:
		return 0.0
	return 1.0 - (elapsed - HOLD) / FADE


def nameString(text, fade=1.0):
	colour = quietColour()
	if fade < 1.0:
		colour = colour.colorWithAlphaComponent_(fade)
	return NSAttributedString.alloc().initWithString_attributes_(
		text or "",
		{
			NSFontAttributeName: NSFont.systemFontOfSize_(NAME_SIZE),
			NSForegroundColorAttributeName: colour,
		},
	)


def nameSize(text):
	size = nameString(text).size()
	return (size.width + 2.0 * NAME_PAD[0], size.height + 2.0 * NAME_PAD[1])


def drawName(view):
	"""The name on a plate, so that it reads over whatever the panel is
	showing — which is type, and often black."""
	fade = getattr(view, "fade", 0.0)
	if fade <= 0.0:
		return
	bounds = view.bounds()
	plate = firstColour(("controlBackgroundColor", "windowBackgroundColor")) \
		or NSColor.textColor()
	plate.colorWithAlphaComponent_(0.92 * fade).set()
	NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
		bounds, NAME_RADIUS, NAME_RADIUS).fill()

	text = nameString(getattr(view, "says", ""), fade)
	size = text.size()
	text.drawAtPoint_((
		bounds.origin.x + (bounds.size.width - size.width) / 2.0,
		bounds.origin.y + (bounds.size.height - size.height) / 2.0))


def nameClass():
	"""The view the name is drawn in. Built once, like the badge's."""
	store = shared()
	if store.nameClass is None:
		def isFlipped(self):
			return False

		def intrinsicContentSize(self):
			return NSMakeSize(*nameSize(getattr(self, "says", "")))

		def drawRect_(self, dirty):
			drawName(self)

		def hitTest_(self, point):
			# It sits over the preview, and the preview is not ours to take
			# clicks from: this is a label, and it is on its way out.
			return None

		store.nameClass = type("GSSharedPreviewName", (NSView,), {
			"isFlipped": isFlipped,
			"intrinsicContentSize": intrinsicContentSize,
			"drawRect_": drawRect_,
			"hitTest_": hitTest_,
		})
	return store.nameClass


def previewPanel(tab, badge=None):
	"""The preview panel, which is where the name goes.

	Not the toolbar: the strip is 30pt and the row of dots is 22 of them, so
	there is nowhere above the dots to put a name. It goes over the bottom of
	the panel instead, which is above the dots and out of the way of them.

	`previewView` is a method on the controller and not one of the properties
	GlyphsApp adds to a tab in Python, so plain attribute access answers a
	**bound method** rather than a view — truthy, and it would have gone on to
	`addSubview_` to fail there. So it is called if it is callable, then
	checked for being a view at all, and for not being an ancestor of the
	badge: that last is how a view which turned out to be the whole tab would
	give itself away rather than putting the name in the middle of the canvas.
	"""
	for name in ("previewView", "previewBackgroundView"):
		found = getattr(tab, name, None)
		if callable(found):
			try:
				found = found()
			except Exception:
				found = None
		if found is None or not hasattr(found, "addSubview_"):
			continue
		try:
			if badge is not None and badge.isDescendantOf_(found):
				continue
		except Exception:
			pass
		return found
	return None


def placeName(badge):
	"""The name's view, put in this tab's preview panel if it is not there yet."""
	panel = previewPanel(getattr(badge, "tab", None), badge)
	if panel is None:
		return None
	view = getattr(badge, "label", None)
	if view is not None and view.superview() is panel:
		return view
	if view is not None:
		try:
			view.removeFromSuperview()
		except Exception:
			pass
	view = nameClass().alloc().initWithFrame_(NSMakeRect(0.0, 0.0, 10.0, 10.0))
	try:
		panel.addSubview_(view)
		view.setTranslatesAutoresizingMaskIntoConstraints_(False)
		# Centred over the dots, which are centred on the strip, and clear of
		# the toolbar. The constant is negative to lift it off the bottom: a
		# bottom pin's constant runs downwards, which is the opposite of what
		# an unflipped view suggests and was settled by watching it move.
		view.centerXAnchor()\
			.constraintEqualToAnchor_(panel.centerXAnchor()).setActive_(True)
		lift = view.bottomAnchor().constraintEqualToAnchor_(panel.bottomAnchor())
		lift.setConstant_(-NAME_ABOVE)
		lift.setActive_(True)
	except Exception:
		try:
			view.removeFromSuperview()
		except Exception:
			pass
		return None
	badge.label = view
	return view


def announce(badge, name):
	"""Say what the panel has just been switched to."""
	view = placeName(badge)
	if view is None:
		return None
	view.says = name
	view.fade = 1.0
	view.invalidateIntrinsicContentSize()
	view.setNeedsDisplay_(True)
	badge.labelBegan = time.monotonic()
	startFrames()
	return view


def stepName(badge, now):
	"""Fade one name along. Answers whether it is still on screen."""
	view = getattr(badge, "label", None)
	began = getattr(badge, "labelBegan", None)
	if view is None or began is None:
		return False
	fade = nameOpacity(now - began)
	if abs(fade - getattr(view, "fade", -1.0)) > 0.005:
		view.fade = fade
		view.setNeedsDisplay_(True)
	if fade > 0.0:
		return True
	dropName(badge)
	return False


def dropName(badge):
	"""Take the name off, if there is one."""
	view = getattr(badge, "label", None)
	badge.labelBegan = None
	badge.label = None
	if view is not None:
		try:
			view.removeFromSuperview()
		except Exception:
			pass


def badgeClass():
	"""The view class, built once for every copy of this file there is.

	Defining an Objective-C class a second time under the same name raises
	rather than shadowing, so the second plugin to load a copy of this module
	must not define its own. It borrows this one.
	"""
	store = shared()
	if store.badgeClass is None:
		def isFlipped(self):
			return False

		def intrinsicContentSize(self):
			return NSMakeSize(*badgeSize())

		def acceptsFirstMouse_(self, event):
			# Clickable without first bringing the window forward: it is a
			# switch on a toolbar, not a document.
			return True

		def drawRect_(self, dirty):
			drawBadge(self)
			# Re-laid every time it is drawn, because this is the one place
			# the bounds are certainly the ones just used.
			self.removeAllToolTips()
			self.addToolTipRect_owner_userData_(self.bounds(), self, None)

		def view_stringForToolTip_point_userData_(self, view, tag, point, data):
			return tipAt(self.bounds(), point.x) or ""

		def mouseDown_(self, event):
			point = self.convertPoint_fromView_(event.locationInWindow(), None)
			self.pressed = dotAt(self.bounds(), point.x)
			self.setNeedsDisplay_(True)

		def mouseUp_(self, event):
			point = self.convertPoint_fromView_(event.locationInWindow(), None)
			index = dotAt(self.bounds(), point.x)
			# Only if it went down and came up on the same dot, so a click
			# can be taken back by sliding off it.
			if index is not None and index == getattr(self, "pressed", None):
				show(index)
			self.pressed = None
			self.setNeedsDisplay_(True)

		store.badgeClass = type("GSSharedPreviewBadge", (NSView,), {
			"isFlipped": isFlipped,
			"intrinsicContentSize": intrinsicContentSize,
			"acceptsFirstMouse_": acceptsFirstMouse_,
			"drawRect_": drawRect_,
			"view_stringForToolTip_point_userData_":
				view_stringForToolTip_point_userData_,
			"mouseDown_": mouseDown_,
			"mouseUp_": mouseUp_,
		})
	return store.badgeClass


# --------------------------------------------------- putting it in the strip

def pinToStrip(badge):
	"""Take the badge out of the strip's arrangement and pin it to the middle.

	`addViewToBottomToolbar:` hands the view to the bottom toolbar's stack
	view, which then settles both where it goes and how big it is, and settles
	both badly. It goes at the head of the trailing group, hard against the
	buttons on the right; and a stack view hands its slack to whichever
	arranged view hugs its content least, which is a contest with the strip's
	own slider that neither is meant to win — the badge either takes the whole
	gap or, if the slider takes it first, is squeezed to nothing.

	Moving it to the stack's centre gravity area answers half of that: that
	area holds the middle only while there is room, and is pushed right as
	soon as the controls on the left crowd it. A centring constraint cannot
	argue with the stack either, whose own constraints are required — one at
	999 is dropped, and one at 1000 wins by squeezing the badge to nothing.

	A plain subview of a stack view is not arranged by it, so it keeps out of
	all of that and can simply be pinned: centred on the strip, flush with the
	bottom of it, at the size the badge answers for itself.

	Answers whether it was pinned. If this ever stops working the badge stays
	arranged, which is where Glyphs put it — the right size, in the wrong
	place, which is worth more than an exception.
	"""
	strip = badge.superview()
	if strip is None or not hasattr(strip, "removeView_"):
		return False
	try:
		strip.removeView_(badge)
		strip.addSubview_(badge)
		badge.setTranslatesAutoresizingMaskIntoConstraints_(False)
		# Where it goes, only. How big it is comes from the badge itself, which
		# has to answer that anyway for the case where none of this worked.
		# The bottom pin is kept hold of: its constant is what the badge slides
		# along, from flush with the bottom of the strip to under it.
		slide = badge.bottomAnchor()\
			.constraintEqualToAnchor_(strip.bottomAnchor())
		slide.setConstant_(tuckedBy(badge))
		slide.setActive_(True)
		badge.slide = slide
		badge.slideTarget = slide.constant()
	except Exception:
		return False
	recentre(badge)
	return True


def centredOn(badge):
	"""What the row is lined up on.

	Not the stack view it sits in. That does not run the whole width of the bar
	in Glyphs — the zoom controls at the right-hand end are outside it — so its
	middle is some 40pt left of the middle of the bar, and the dots sat there
	while the name sat in the middle of the panel above them. The panel does
	run the whole width, and it is what the name is centred on, so centring
	both on the one thing is what keeps them lined up whatever the window does.

	Falls back to the strip, which is where they were: off centre, but on the
	bar.
	"""
	panel = previewPanel(getattr(badge, "tab", None), badge)
	return panel if panel is not None else badge.superview()


def recentre(badge):
	"""Line the row up, and line it up again if what it lines up on changes.

	Asked on every refresh because the panel is not necessarily there to be
	found when the tab opens.
	"""
	wanted = centredOn(badge)
	if wanted is None or getattr(badge, "centre", None) is wanted:
		return False
	standing = getattr(badge, "centrePin", None)
	if standing is not None:
		try:
			standing.setActive_(False)
		except Exception:
			pass
	try:
		pin = badge.centerXAnchor()\
			.constraintEqualToAnchor_(wanted.centerXAnchor())
		pin.setActive_(True)
	except Exception:
		return False
	badge.centrePin = pin
	badge.centre = wanted
	return True


def panelOpen(tab):
	"""Whether that tab's preview panel is open at all."""
	try:
		return float(tab.previewHeight) >= PANEL_MIN_HEIGHT
	except Exception:
		return False


def wantsShowing(badge):
	"""Whether this badge should be in view: whenever the panel is open.

	The whole time it is open, not only while the pointer is passing: a plugin
	holding the preview with nothing on screen to account for it is the thing
	this exists to prevent, and a switch you have to go looking for accounts
	for nothing. With the panel shut there is nothing being previewed and
	nothing to switch, so it goes away.
	"""
	if not shared().providers:
		return False
	return panelOpen(getattr(badge, "tab", None))


def tuckedBy(badge):
	"""How far down the badge sits when it is out of the way.

	Its own height, so that none of it is left peeking over the bottom edge of
	the strip. Positive, and measured against the strip is unflipped: a bottom
	pin's constant runs down the way whichever way the view's own y runs, and
	the sign here was settled by watching the badge move rather than by
	reasoning about which of the two it would follow.
	"""
	height = badge.frame().size.height
	if height <= 0.0:
		height = badgeSize()[1]
	return height


def eased(part):
	"""How far along the slide is, from how far through its time it is.

	A cubic ease-out: off the mark at once and settling slowly, so that the
	moment the pointer arrives or leaves is the moment the badge visibly
	moves. That is what makes a reveal feel answered. A straight line reads as
	mechanical over this short a distance, and an ease-in reads as a stall.
	"""
	part = min(1.0, max(0.0, part))
	return 1.0 - (1.0 - part) ** 3


def startSlide(badge, target, duration, done=None):
	"""Set the badge moving towards a constant, or put it there at once.

	Stepped from a timer of our own rather than handed to
	`constraint.animator()`, which is CoreAnimation underneath and does not
	advance at all while the display is asleep. That strands the badge partway,
	and it makes the slide untestable on a machine nobody is looking at — which
	is most machines that run the tests.
	"""
	if duration <= 0.0:
		badge.slideBegan = None
		badge.slide.setConstant_(target)
		if done is not None:
			done()
		return
	badge.slideFrom = badge.slide.constant()
	badge.slideTo = target
	badge.slideOver = duration
	badge.slideDone = done
	badge.slideBegan = time.monotonic()
	startFrames()


def stepSlide(badge, now):
	"""Move one badge along. Answers whether it has further to go."""
	began = getattr(badge, "slideBegan", None)
	if began is None:
		return False
	over = getattr(badge, "slideOver", 0.0) or 0.0
	part = 1.0 if over <= 0.0 else (now - began) / over
	if part >= 1.0:
		badge.slide.setConstant_(badge.slideTo)
		badge.slideBegan = None
		done, badge.slideDone = getattr(badge, "slideDone", None), None
		if done is not None:
			done()
		return False
	badge.slide.setConstant_(
		badge.slideFrom + (badge.slideTo - badge.slideFrom) * eased(part))
	return True


def stepEverything():
	"""One frame of everything moving. Answers whether anything still is."""
	now = time.monotonic()
	going = False
	for badge in list(shared().badges):
		for step in (stepSlide, stepName):
			try:
				if step(badge, now):
					going = True
			except Exception:
				try:
					badge.slideBegan = badge.labelBegan = None
				except Exception:
					pass
	return going


def startFrames():
	"""Run the frames — only while something is actually moving. This is sixty
	a second, against the quarter-second tick that only asks questions."""
	store = shared()
	if store.frameTimer is not None or store.warden is None:
		return
	store.frameTimer = \
		NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
			FRAME, store.warden, b"slid:", None, True)
	NSRunLoop.currentRunLoop().addTimer_forMode_(
		store.frameTimer, NSRunLoopCommonModes)


def stopFrames():
	store = shared()
	if store.frameTimer is None:
		return
	try:
		store.frameTimer.invalidate()
	except Exception:
		pass
	store.frameTimer = None


def slideBadge(badge, showing, animated=True):
	"""Bring the badge up into the strip, or tuck it back under the bottom.

	Sliding rather than appearing, because it comes and goes under the pointer:
	something that pops into place where the cursor already is reads as a
	misclick waiting to happen, where something that slides up out of the
	bottom edge reads as what it is — a tab, coming out of the bar it belongs
	to. Which is why it is drawn as a tab, square along the bottom.

	Hidden at the far end of the slide as well as tucked, so that a badge out
	of sight is out of the way with it: taking no clicks, and not left to the
	strip to clip.
	"""
	badge.showing = bool(showing)
	pin = getattr(badge, "slide", None)
	if pin is None:
		# Never pinned, so there is nothing to slide along: the badge is where
		# Glyphs put it, and showing it or not is all there is to do.
		badge.setHidden_(not showing)
		return

	target = 0.0 if showing else tuckedBy(badge)
	standing = getattr(badge, "slideTarget", None)
	# Already going there, so leave it going: the quarter-second tick asks this
	# question all through a slide, and one started over every quarter second
	# never lands. But *being put* somewhere is not being sent there — a refresh
	# that is not animating means be there now, and then where the badge
	# actually is, is the question, not where it was last sent.
	settled = abs(pin.constant() - target) < 0.5
	if standing is not None and abs(standing - target) < 0.5 \
			and (animated or settled):
		return
	badge.slideTarget = target
	if showing:
		badge.setHidden_(False)

	# Hidden at the end of the way out, and only then. A badge called back
	# partway does not need guarding against this one firing late: a badge has
	# one slide at a time, and starting another replaces what the last was
	# going to do when it landed.
	startSlide(badge, target, SLIDE if animated else 0.0,
	           None if showing else lambda: badge.setHidden_(True))


def badgeFor(tab):
	for badge in shared().badges:
		if getattr(badge, "tab", None) is tab:
			return badge
	return None


def attach(tab):
	"""Give a tab a badge, if it has not got one."""
	store = shared()
	if tab is None or not hasattr(tab, "addViewToBottomToolbar_"):
		return None
	standing = badgeFor(tab)
	if standing is not None:
		return standing

	width, height = badgeSize()
	badge = badgeClass().alloc().initWithFrame_(
		NSMakeRect(0.0, 0.0, width, height))
	badge.tab = tab
	badge.pressed = None
	badge.showing = False
	badge.label = None
	badge.labelBegan = None
	badge.centre = None
	badge.centrePin = None
	badge.setHidden_(True)
	tab.addViewToBottomToolbar_(badge)
	pinToStrip(badge)
	store.badges.append(badge)
	refresh()
	return badge


def detach(tab):
	"""Take a tab's badge back out, when it closes."""
	badge = badgeFor(tab)
	if badge is None:
		return
	dropName(badge)
	try:
		badge.removeFromSuperview()
	except Exception:
		pass
	try:
		shared().badges.remove(badge)
	except ValueError:
		pass


def removeAll():
	"""Every badge, out of every tab. When the last plugin goes."""
	store = shared()
	for badge in list(store.badges):
		dropName(badge)
		try:
			badge.removeFromSuperview()
		except Exception:
			pass
	store.badges = []


def refresh(animated=True):
	"""Bring every badge up to date with what the panel is showing.

	In view the whole time that tab's preview panel is open, and slid away
	under the bottom of the strip when it is not. A change of mode also puts
	the new mode's name up over the panel for a moment.
	Sliding is what `animated` is about, and it is only ever turned off by a
	test wanting the badge to be somewhere definite rather than on its way.
	"""
	store = shared()
	name = currentName()
	# Only a change worth announcing, and only once however many badges hear
	# about it. The first refresh after a plugin registers is not a switch.
	switched = store.told is not None and name != store.told
	store.told = name
	for badge in list(store.badges):
		try:
			# The panel may not have been there to line up on when the tab
			# opened, and it is what the name is centred on.
			recentre(badge)
			wanted = wantsShowing(badge)
			slideBadge(badge, wanted, animated)
			badge.invalidateIntrinsicContentSize()
			badge.setNeedsDisplay_(True)
			# Not while the row itself is being put somewhere rather than
			# sliding there: that is a test settling the state, not a switch.
			if switched and animated and wanted:
				announce(badge, name)
			elif not wanted:
				dropName(badge)
		except Exception:
			pass


# ------------------------------------------------------------ the menu entry

# What the entry says, and it does not change with what is showing. Glyphs
# remembers a keyboard shortcut against the title of the item it was given to,
# so an entry naming the mode it would switch to — the obvious thing to write
# there — would lose its shortcut the first time it was used. It says what it
# does instead, which is the same whatever the panel is showing.
MENU_TITLE = {
	"en": "Next Preview Mode",
	"de": "Nächster Vorschaumodus",
	"fr": "Mode d'aperçu suivant",
}


def viewMenu():
	"""Glyphs' View menu.

	`Glyphs.menu[VIEW_MENU]` answers the menu bar item that holds it rather
	than the menu, so this goes the one step further to the submenu — which is
	all `append` on one of those items is, and this way the entry does not
	depend on that convenience being there to be added or, more to the point,
	to be taken away again.

	Imported here rather than at the top for the reason the rest of GlyphsApp
	is: the module has to import outside Glyphs, where there is no menu bar and
	the registry and the drawing are still worth testing.
	"""
	try:
		from GlyphsApp import Glyphs, VIEW_MENU
		return Glyphs.menu[VIEW_MENU].submenu()
	except Exception:
		return None


# The submenu it goes in: View → Navigation, which is where Glyphs keeps Show
# Next Glyph, Next Master, Next Layer — every other "the next one of these"
# there is. Its title is all there is to find it by, so these are the titles
# Glyphs itself ships, read out of the MainMenu.strings of each localisation in
# the application bundle. A title not in here — a language added since, or the
# menu reorganised — falls back to the View menu itself, which is where the
# entry was before this: one level further out than it should be, rather than
# nowhere at all.
NAVIGATION = (
	"Navigation",                    # English, German, French
	"Navigace",                      # Czech
	"Navegación",                    # Spanish
	"Navigazione",                   # Italian
	"Navegação",                     # Portuguese
	"Gezinme",                       # Turkish
	"التنقل",                          # Arabic
	"グリフのナビゲーション",                    # Japanese
	"네비게이션",                        # Korean
	"Навигация",                     # Russian
	"导航",                           # Chinese, simplified
	"導覽",                           # Chinese, traditional
)


def navigationMenu(menu):
	"""View → Navigation, or the View menu itself if there is no such thing.

	Matched on the title of the item and of the submenu both, because Glyphs
	gives each of them the name and either could be the one that changes.
	"""
	if menu is None:
		return None
	try:
		for item in menu.itemArray():
			found = item.submenu()
			if found is None:
				continue
			if item.title() in NAVIGATION or found.title() in NAVIGATION:
				return found
	except Exception:
		pass
	return menu


def menuTitle():
	try:
		from GlyphsApp import Glyphs
		return Glyphs.localize(MENU_TITLE)
	except Exception:
		return MENU_TITLE["en"]


def installMenu():
	"""Put the entry in the View menu.

	In **View → Navigation**, with Show Next Glyph and Next Master and the rest
	of them: it is the next one of something, and that is where Glyphs keeps
	those.

	The dots are a switch you have to be looking at the toolbar to use, and
	they are only there while the preview panel is open. This is the same
	switch for the rest of the time, and the only one that can be given a
	keyboard shortcut: Glyphs' settings list every menu item there is under
	Shortcuts, and nothing else a plugin puts on screen.

	One entry however many plugins there are, for the reason there is one row
	of dots: it is the registry's and not the first plugin's to have loaded a
	copy of this file, it goes up when the first plugin registers, and it comes
	down when the last one leaves.
	"""
	store = shared()
	if store.menuItem is not None or store.warden is None:
		return store.menuItem
	menu = navigationMenu(viewMenu())
	if menu is None:
		return None
	item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
		menuTitle(), b"switchPreview:", "")
	# A menu item does not keep its target alive. The registry is what holds
	# the warden, and taking this back out is part of the last plugin going.
	item.setTarget_(store.warden)
	try:
		menu.addItem_(item)
	except Exception:
		return None
	store.menuItem = item
	return item


def removeMenu():
	"""Take the entry back out, of whichever menu it is actually in.

	Asked of the item rather than of the View menu again, so that an entry which
	somehow ended up somewhere else still comes out of where it is rather than
	being left behind pointing at a warden that has gone.
	"""
	store = shared()
	item, store.menuItem = store.menuItem, None
	if item is None:
		return
	try:
		item.menu().removeItem_(item)
	except Exception:
		pass


# ---------------------------------------------------- finding the tabs itself

def wardenClass():
	"""The object the notifications and the timer are addressed to.

	Built once and held by the registry, for the same reason the view class is.
	"""
	store = shared()
	if store.wardenClass is None:
		def tabDidOpen_(self, notification):
			attach(notification.object())

		def tabWillClose_(self, notification):
			detach(notification.object())

		def tick_(self, timer):
			# Asked for again every tick because the menu bar may not have
			# been there when the first plugin registered — a reporter can be
			# switched on while Glyphs is still putting itself together — and
			# nothing announces it afterwards. Costs an attribute once it is
			# up: the entry is looked at, not made again.
			installMenu()
			refresh()

		def slid_(self, timer):
			if not stepEverything():
				stopFrames()

		def switchPreview_(self, sender):
			stepMode()

		def validateMenuItem_(self, item):
			# Greyed out when there is nothing to switch between — the rule the
			# dots follow by not being drawn at all. pyobjc takes the signature
			# for this off the informal protocol, so a plain True or False is
			# the BOOL the menu is asking for.
			return modeCount() > 1

		store.wardenClass = type("GSSharedPreviewBadgeWarden", (NSObject,), {
			"tabDidOpen_": tabDidOpen_,
			"tabWillClose_": tabWillClose_,
			"tick_": tick_,
			"slid_": slid_,
			"switchPreview_": switchPreview_,
			"validateMenuItem_": validateMenuItem_,
		})
	return store.wardenClass


def startWatching():
	"""Watch for tabs, and for the panel being opened and shut."""
	store = shared()
	if store.warden is not None:
		return
	store.warden = wardenClass().alloc().init()

	# Imported here rather than at the top: this module is a drop-in, and
	# should not fail to import outside Glyphs — where the registry and the
	# drawing are still perfectly testable.
	from GlyphsApp import Glyphs, TABDIDOPEN, TABWILLCLOSE

	center = NSNotificationCenter.defaultCenter()
	center.addObserver_selector_name_object_(
		store.warden, b"tabDidOpen:", TABDIDOPEN, None)
	center.addObserver_selector_name_object_(
		store.warden, b"tabWillClose:", TABWILLCLOSE, None)

	# Tabs already open when the first plugin registers get one too.
	try:
		for font in list(Glyphs.fonts):
			try:
				for tab in font.tabs:
					attach(tab)
			except Exception:
				pass
	except Exception:
		pass

	# Nothing tells a plugin that the preview panel was opened or shut, so it
	# is asked. A tick that finds nothing changed does nothing.
	store.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
		TICK, store.warden, b"tick:", None, True)
	NSRunLoop.currentRunLoop().addTimer_forMode_(
		store.timer, NSRunLoopCommonModes)


def stopWatching():
	"""Nothing offers a preview any more: stop, and leave no view behind."""
	store = shared()
	stopFrames()
	removeMenu()
	if store.timer is not None:
		try:
			store.timer.invalidate()
		except Exception:
			pass
		store.timer = None
	if store.warden is not None:
		try:
			NSNotificationCenter.defaultCenter().removeObserver_(store.warden)
		except Exception:
			pass
		store.warden = None
	removeAll()


# ----------------------------------------------------------------- the API

def register(identifier, name, isActive, activate, deactivate):
	"""Offer a preview. The badge starts naming it and the arrows reach it.

	`identifier` is yours and has to be stable — it is what unregister takes,
	and what keeps a plugin that registers twice from appearing twice.
	"""
	store = shared()
	provider = {
		"id": identifier,
		"name": name,
		"isActive": isActive,
		"activate": activate,
		"deactivate": deactivate,
	}
	for index, standing in enumerate(store.providers):
		if standing["id"] == identifier:
			store.providers[index] = provider
			break
	else:
		store.providers.append(provider)
	startWatching()
	# Asked of every plugin that registers rather than done once inside
	# startWatching, which the second and later ones never reach: a copy of this
	# file older than the entry could have been the one that started the
	# watching, and then the entry would be nobody's to put up.
	installMenu()
	refresh()
	return provider


def unregister(identifier):
	"""Stop offering it. The last one out takes the badge with it."""
	store = shared()
	store.providers = [p for p in store.providers if p["id"] != identifier]
	if not store.providers:
		stopWatching()
	else:
		refresh()
