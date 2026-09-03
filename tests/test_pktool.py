"""What the tool does with a composite that has no wall of its own.

The merge itself is `test_bkmerge`. This is the layer above it: whether a
composite is left to its components at all, and whether the handles put on one
so it can be seen and grabbed can end up written down as if it had meant them.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
from types import SimpleNamespace
from Foundation import NSMakeRect, NSPoint

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name):
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location('pk_' + name, RESOURCES / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	sys.modules['pk_' + name] = module
	spec.loader.exec_module(module)
	return module


tool_module = _load('PKTool')
preview_module = tool_module.preview  # the same object the plugin drew with
store_module = tool_module.store  # likewise for what writes the bubbles
from GlyphsApp import GSLayer  # the conftest stub, after it has been installed

MASTER_ID = 'm1'
MASTER = type('Master', (), {'id': MASTER_ID, 'italicAngle': 0, 'xHeight': 508,
		'name': 'Medium', 'descender': -200, 'ascender': 800})()

O_WIDTH, ACCENT_WIDTH, ACCENT_DX = 600, 454, 74
O_L = [(114, -16), (30, 98), (8, 168), (0, 252), (7, 338), (29, 408), (115, 524)]
O_R = [(-114, -16), (-30, 98), (-8, 168), (0, 252), (-7, 338), (-29, 408), (-115, 524)]
ACCENT_L = [(7, 571), (121, 700)]
ACCENT_R = [(0, 572), (-83, 700)]


class UserData(dict):
	def __missing__(self, key):
		return None


class Glyph:
	def __init__(self, name, layer):
		self.name = name
		self.layers = [layer]
		self.undo = 0

	def beginUndo(self):
		self.undo += 1

	def endUndo(self):
		self.undo -= 1


class Layer(GSLayer):
	isMasterLayer = True
	associatedMasterId = MASTER_ID

	def __init__(self, name, width, nodesL=None, nodesR=None, paths=0,
			components=()):
		self.name = name
		self.selection = []
		self.width = width
		self.paths = [object()] * paths
		self.components = list(components)
		self.shapes = self.paths + self.components
		self.userData = UserData()
		self.tempData = UserData()
		self.bounds = NSMakeRect(0, 0, width, 700)
		self.master = MASTER
		if nodesL is not None:
			self.userData['PolyKernNodesL'] = nodesL
		if nodesR is not None:
			self.userData['PolyKernNodesR'] = nodesR
		self.parent = Glyph(name, self)

	def font(self):
		return None

	def associatedFontMaster(self):
		return MASTER


class Component:
	def __init__(self, layer, tx=0.0, ty=0.0):
		self.componentLayer = layer
		self.transform = (1.0, 0.0, 0.0, 1.0, tx, ty)
		self.alignment = 0
		self.automaticAlignment = True


@pytest.fixture
def tool():
	# NO __init__: it builds a window. Every method under test is a plain
	# python_method that never reaches for one.
	return tool_module.PolyKernTool.__new__(tool_module.PolyKernTool)


@pytest.fixture
def oh():
	o = Layer('o', O_WIDTH, nodesL=O_L, nodesR=O_R, paths=2)
	accent = Layer('circumflexcomb', ACCENT_WIDTH, nodesL=ACCENT_L,
			nodesR=ACCENT_R, paths=1)
	ocirc = Layer('ocircumflex', O_WIDTH, components=[
			Component(o), Component(accent, tx=ACCENT_DX)])
	return o, accent, ocirc


# --- Being left to the components ------------------------------------------


def test_a_composite_is_left_to_its_components(oh):
	o, accent, ocirc = oh
	ocirc.userData['PolyKernNodesL'] = [(0, -16), (0, 700)]
	assert store_module.mergeFromComponents(ocirc, store_module.LEFT) is True
	assert not ocirc.userData['PolyKernNodesL'], 'the wall in the way is gone'
	assert ocirc.parent.undo == 0, 'opened and closed'


def test_a_glyph_that_draws_its_own_ink_is_never_cleared(oh):
	o, accent, ocirc = oh
	assert store_module.mergeFromComponents(o, store_module.LEFT) is False
	assert o.userData['PolyKernNodesL'] == O_L


def test_a_composite_with_nothing_to_borrow_is_drawn_after_all(oh):
	"""Both components carry the default line, so the merge would be a line on
	the origin - no wall at all. Better to generate one."""
	o, accent, ocirc = oh
	o.userData['PolyKernNodesL'] = [(0, -16), (0, 524)]
	accent.userData['PolyKernNodesL'] = [(0, 571), (0, 700)]
	assert store_module.mergeFromComponents(ocirc, store_module.LEFT) is False


def test_a_side_pointed_somewhere_by_hand_is_left_alone(oh):
	o, accent, ocirc = oh
	ocirc.userData['PolyKernReferL'] = 'e'
	assert store_module.mergeFromComponents(ocirc, store_module.LEFT) is False
	assert ocirc.userData['PolyKernReferL'] == 'e'


# --- The handles put on a borrowing layer ----------------------------------


def wall_of(bubbles, side='nodesL'):
	return [(round(n.x), round(n.y)) for n in bubbles[side]]


def test_the_handles_sit_on_the_wall_the_composite_resolves_to(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(ocirc)
	assert wall_of(bubbles) == O_L + [(81, 571), (195, 700)]


def test_the_borrowed_handles_are_dropped_when_the_component_moves(tool, oh):
	"""Edit the circumflex and every glyph wearing one has to follow. The
	cache is keyed on the layer's own width, which a component edit does not
	touch, so nothing here said the handles had gone out of date."""
	o, accent, ocirc = oh
	tool.loadNodesFromLayer(ocirc)
	accent.userData['PolyKernNodesL'] = [(40, 571), (160, 700)]
	assert wall_of(tool.loadNodesFromLayer(ocirc))[-2:] == [(114, 571), (234, 700)]


def test_a_drag_in_progress_survives_a_reload(tool, oh):
	"""The other half of the same rule: a reload must drop what went stale
	underneath, and keep what somebody is holding."""
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(ocirc)
	bubbles['nodesL'][-1].pos = NSPoint(300, 700)
	assert wall_of(tool.loadNodesFromLayer(ocirc))[-1] == (300, 700)


def test_an_untouched_composite_is_not_written_down(tool, oh):
	"""Switching glyphs saves whatever is in tempData. On a composite that is
	the borrowed wall, and writing it back freezes the glyph at what its
	components happened to look like."""
	o, accent, ocirc = oh
	tool.loadNodesFromLayer(ocirc)
	accent.userData['PolyKernNodesL'] = [(40, 571), (160, 700)]  # moved since
	tool.saveNodesToLayer(ocirc)
	assert not ocirc.userData['PolyKernNodesL'], 'still borrowing'


def test_a_composite_somebody_dragged_keeps_what_was_dragged(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(ocirc)
	bubbles['nodesL'][-1].pos = NSPoint(300, 700)
	tool.saveNodesToLayer(ocirc)
	stored = ocirc.userData['PolyKernNodesL']
	assert stored and tuple(stored[-1]) == (300, 700)


def test_a_mirrored_side_does_not_fight_a_drag_on_the_other_one(tool, oh):
	"""`circumflexcomb` with its right side set to `=|`. A mirrored side owns
	no nodes, so it is filled in from the wall the layer resolves to - but what
	it resolves to is the OTHER SIDE OF THIS LAYER, live, which is precisely
	what a drag is moving. Counted as borrowed it went out of date on the first
	pixel of every drag and took the drag with it."""
	o, accent, ocirc = oh
	del accent.userData['PolyKernNodesR']
	accent.userData['PolyKernMirrorR'] = 1
	bubbles = tool.loadNodesFromLayer(accent)
	bubbles['nodesL'][0].pos = NSPoint(40, 571)
	assert wall_of(tool.loadNodesFromLayer(accent))[0] == (40, 571)


def test_only_this_tools_own_nodes_stay_selected(tool, oh):
	"""SelectTool finds a segment under the cursor by its own means, whatever
	`elementAtPoint:` answers, and the outline is not this tool's to select."""
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	handle = bubbles['nodesL'][0]
	accent.selection = [handle, object()]  # a segment SelectTool went and found
	tool.keepOnlyBubbleNodes(accent)
	assert accent.selection == [handle]


# --- The coordinates of the selected node ----------------------------------


def test_the_strip_shows_the_one_selected_node(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	handle = bubbles['nodesL'][0]
	accent.selection = [handle]
	assert tool.selectedBubbleNode(accent) == (handle, False)
	assert tool.storedCoordinates(accent, handle, False) == (7.0, 571.0)


def test_a_right_side_node_reads_back_from_its_own_advance(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	handle = bubbles['nodesR'][0]  # sits at 454 on the canvas
	accent.selection = [handle]
	assert tool.selectedBubbleNode(accent) == (handle, True)
	assert tool.storedCoordinates(accent, handle, True) == (0.0, 572.0)


def test_two_selected_nodes_are_not_one_pair_of_coordinates(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	accent.selection = list(bubbles['nodesL'])
	assert tool.selectedBubbleNode(accent) == (None, False)


def test_typing_a_coordinate_moves_the_node(tool, oh):
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	handle = bubbles['nodesL'][0]
	accent.selection = [handle]
	assert tool.moveBubbleNodeTo(accent, handle, False, 40, 571) is True
	assert [tuple(n) for n in accent.userData['PolyKernNodesL']] == [
			(40, 571), (121, 700)]
	# TYPING THE SAME NUMBERS AGAIN IS NOT AN EDIT: no undo step, no write.
	assert tool.moveBubbleNodeTo(accent, handle, False, 40, 571) is False


def test_a_node_typed_past_its_neighbour_lands_in_order(tool, oh):
	"""A wall is read bottom to top, so the list has to stay that way."""
	o, accent, ocirc = oh
	bubbles = tool.loadNodesFromLayer(accent)
	handle = bubbles['nodesL'][0]
	accent.selection = [handle]
	tool.moveBubbleNodeTo(accent, handle, False, 40, 900)
	stored = [tuple(n) for n in accent.userData['PolyKernNodesL']]
	assert stored == [(121, 700), (40, 900)]


def test_the_coordinate_strip_is_shaped_like_the_one_glyphs_draws():
	"""The strip stands in for Glyphs' own X and Y box, so it copies it.

	MEASURED IN THE RUNNING APP, not guessed at: Glyphs' box is the next view
	along in the info bar's stack, 78 by 46, its labels 13 wide standing at
	x 8 and its fields 53 wide at x 21, both rows 17 tall at y 3 and y 24.
	A row two points too tall centres its line one point too high, which is
	the whole of what was wrong with this and is invisible in a screenshot
	until it is stood next to the box it is copying.
	"""
	tool = tool_module.PolyKernTool.__new__(tool_module.PolyKernTool)
	tool.settings()
	view = tool.coordsView
	view.layoutSubtreeIfNeeded()
	size = view.frame().size
	assert (size.width, size.height) == (78.0, 46.0)
	frames = [(f.origin.x, f.origin.y, f.size.width, f.size.height)
			for f in (sub.frame() for sub in view.subviews())]
	assert frames == [(8.0, 24.0, 13.0, 17.0), (21.0, 24.0, 53.0, 17.0),
			(8.0, 3.0, 13.0, 17.0), (21.0, 3.0, 53.0, 17.0)]


# --- What the preview draws when nothing is typed --------------------------


class Tab:
	def __init__(self, layers):
		self.layers = layers


class Font:
	def __init__(self, tab):
		self.currentTab = tab


def _tabGlyph(name):
	"""A layer whose glyph answers to a master id, the way a real one does."""
	layer = Layer(name, 500)
	layer.parent.layers = {MASTER_ID: layer}
	return layer


def test_an_empty_preview_field_reads_the_tab_in_front():
	from GlyphsApp import GSControlLayer
	a, v = _tabGlyph('A'), _tabGlyph('V')
	tab = Tab([a, GSControlLayer(), v])  # a line break is not a glyph
	layers = preview_module.currentTabLayers(Font(tab), MASTER)
	assert [layer.name for layer in layers] == ['A', 'V']


def test_a_tab_with_nothing_in_it_is_not_an_answer():
	"""None, not [] - the caller falls through to the string it ships with."""
	assert preview_module.currentTabLayers(Font(Tab([])), MASTER) is None
	assert preview_module.currentTabLayers(Font(None), MASTER) is None


def test_the_kern_figures_always_stand_clear_below_the_line():
	"""They measure the bands over the type, so they may never sit on one.

	The room for them is taken off the height the line is fitted into. Taken
	off and then centred, it was reserved ABOVE the type instead: at the
	fitting size the line stood on the floor of the box, the figures met the
	clip, and the clip pushed them back up onto the bands.
	"""
	foot = preview_module.PREVIEW_FOOT_ROOM
	lineBox = 12.0  # what 9pt figures occupy, rounded up
	for usableHeight in (60.0, 120.0, 190.0, 400.0):
		tallest = usableHeight - preview_module.KERN_LABEL_ROOM
		for lineHeight in (tallest, tallest * 0.75, tallest * 0.5, 1.0):
			emBottom = preview_module.previewEmBottom(usableHeight, lineHeight)
			labelY = preview_module.kernLabelY(emBottom)
			assert labelY >= foot, f'cut off the foot at {usableHeight}'
			assert labelY + lineBox <= emBottom, f'on the band at {usableHeight}'


def test_the_band_the_eye_reads_is_what_gets_centred():
	"""Nearly every letter stands between the baseline and the cap height. The
	ascender above and the descender below are reached by a few, and empty
	space does not read as part of a word - so centring the em box leaves the
	line looking high, which is what it did, twice."""
	foot = preview_module.PREVIEW_FOOT_ROOM
	for usableHeight in (190.0, 238.0, 400.0):
		lineHeight = (usableHeight - preview_module.KERN_LABEL_ROOM) * 0.55
		capBand = lineHeight * preview_module.CAP_BAND_EM
		emBottom = preview_module.previewEmBottom(usableHeight, lineHeight, capBand)
		# A SHADE ABOVE THE MIDDLE: dead centre reads low.
		middle = foot + usableHeight * (0.5 + preview_module.OPTICAL_LIFT)
		assert emBottom + capBand == pytest.approx(middle), usableHeight
		assert middle > foot + usableHeight / 2.0, 'the lift went the wrong way'
		# WHICH IS LOWER THAN CENTRING THE EM BOX, by the difference between
		# the two middles - a tenth of the em, on ordinary metrics.
		assert emBottom < foot + (usableHeight - lineHeight) / 2.0


def test_the_band_comes_from_the_masters_own_cap_height():
	"""So the centring follows the file rather than an assumption about it."""
	master = SimpleNamespace(capHeight=700.0, descender=-250.0, ascender=750.0)
	assert preview_module.capBandFor(master, 0.2) == pytest.approx(
		(250.0 + 350.0) * 0.2)
	# A DIFFERENT CAP HEIGHT MOVES IT, which is the whole reason for asking.
	tall = SimpleNamespace(capHeight=800.0, descender=-250.0, ascender=750.0)
	assert preview_module.capBandFor(tall, 0.2) > preview_module.capBandFor(master, 0.2)
	# AND SO DOES A DIFFERENT DESCENDER: the band is measured up from the
	# bottom of the em box, not from a number that is usually 250.
	shallow = SimpleNamespace(capHeight=700.0, descender=-200.0, ascender=750.0)
	assert preview_module.capBandFor(shallow, 0.2) == pytest.approx(
		(200.0 + 350.0) * 0.2)


def test_a_master_with_no_cap_height_is_no_band_at_all():
	"""Nothing to go on, so `previewEmBottom` falls back to CAP_BAND_EM."""
	for master in (SimpleNamespace(capHeight=0, descender=-250.0),
			SimpleNamespace(capHeight=None, descender=-250.0),
			SimpleNamespace(descender=-250.0)):
		assert preview_module.capBandFor(master, 0.2) is None


def test_a_master_with_no_cap_height_still_gets_a_band():
	"""Given none, CAP_BAND_EM of the line stands in."""
	emBottom = preview_module.previewEmBottom(238.0, 150.0)
	withStandIn = preview_module.previewEmBottom(
		238.0, 150.0, 150.0 * preview_module.CAP_BAND_EM)
	assert emBottom == pytest.approx(withStandIn)


def test_the_em_box_is_never_pushed_off_the_top():
	"""The band wants the line lower; the box is only so tall.

	UP TO THE TALLEST LINE THERE CAN BE. `drawPreview` caps the scale at
	(usableHeight - KERN_LABEL_ROOM) over the em, so the figures' room is
	always spare - a line taller than that is not a case, it is arithmetic
	that cannot happen.
	"""
	foot = preview_module.PREVIEW_FOOT_ROOM
	for usableHeight in (120.0, 190.0, 238.0, 400.0):
		tallest = usableHeight - preview_module.KERN_LABEL_ROOM
		for lineHeight in (tallest, tallest * 0.75, tallest * 0.4):
			emBottom = preview_module.previewEmBottom(usableHeight, lineHeight)
			assert emBottom + lineHeight <= foot + usableHeight + 0.01, \
					f'{lineHeight} of {usableHeight}'


def test_the_foot_is_a_margin_now_not_a_row_of_switches():
	"""Everything on the preview sits along the top - the size slider and the
	gear. What was reserved under the drawing was holding it up."""
	assert preview_module.PREVIEW_FOOT_ROOM < preview_module.PREVIEW_TOP_ROOM
	assert preview_module.PREVIEW_FOOT_ROOM <= 12.0


# --- Walking a tab ----------------------------------------------------------
# `tab.layers` has no `__len__`, and these two used to walk it by index against
# a 4096 sentinel rather than iterate it. They iterate now, which is the part
# worth holding still.


def test_the_pairs_are_the_adjacent_ones_and_a_break_ends_the_run():
	from GlyphsApp import GSControlLayer
	a, v, o = _tabGlyph('A'), _tabGlyph('V'), _tabGlyph('o')
	tab = Tab([a, v, GSControlLayer(), o])  # A V, then a line break, then o
	pairs = store_module.previewPairs(tab)
	assert [(left.name, right.name) for left, right in pairs] == [('A', 'V')]


def test_a_layer_is_found_at_its_own_place_in_the_tab():
	from GlyphsApp import GSControlLayer
	a, v = _tabGlyph('A'), _tabGlyph('V')
	tab = Tab([a, GSControlLayer(), v])  # the break counts as a position
	assert store_module.tabIndexOf(tab, v) == 2
	assert store_module.tabIndexOf(tab, _tabGlyph('o')) is None


# ---------------------------------------------------------------------------
# THE TOOLBAR ICON
#
# Glyphs draws a tool icon at the image's own size, so the artwork's margins
# come off the mark. These check that the margins are measured away rather than
# demanded of whoever draws the next icon.
# ---------------------------------------------------------------------------

from Foundation import NSMakeSize  # noqa: E402
from AppKit import NSImage, NSColor, NSRectFill  # noqa: E402

Tool = tool_module.PolyKernTool
ARTWORK = RESOURCES / Tool.TOOLBAR_ICON


class _Sizer:
	"""Stands in for the tool: the icon methods only want these three numbers."""
	INK_SEARCH_SCALE = Tool.INK_SEARCH_SCALE
	INK_SEARCH_FLOOR = Tool.INK_SEARCH_FLOOR
	TOOLBAR_ICON_HEIGHT = Tool.TOOLBAR_ICON_HEIGHT
	TOOLBAR_ICON_CANVAS = Tool.TOOLBAR_ICON_CANVAS
	inkBounds = Tool.inkBounds
	trimmedIcon = Tool.trimmedIcon


@pytest.fixture
def sizer():
	return _Sizer()


def _painted(page, ink):
	"""An image `page` big with one solid rectangle `ink` in it. -> NSImage"""
	image = NSImage.alloc().initWithSize_(NSMakeSize(*page))
	image.lockFocus()
	NSColor.blackColor().set()
	NSRectFill(NSMakeRect(*ink))
	image.unlockFocus()
	return image


def test_the_ink_is_found_where_it_was_painted(sizer):
	found = sizer.inkBounds(_painted((40, 40), (5, 8, 10, 20)))
	assert found is not None
	got = (found.origin.x, found.origin.y, found.size.width, found.size.height)
	assert got == pytest.approx((5, 8, 10, 20), abs=0.5)


def test_a_blank_page_has_no_ink(sizer):
	assert sizer.inkBounds(NSImage.alloc().initWithSize_(NSMakeSize(20, 20))) is None


def test_ink_that_fills_the_page_is_the_page(sizer):
	found = sizer.inkBounds(_painted((16, 24), (0, 0, 16, 24)))
	assert (found.size.width, found.size.height) == pytest.approx((16, 24), abs=0.5)


def test_the_shipped_artwork_is_readable_and_has_ink_in_it(sizer):
	"""Whatever it happens to be. It has been trimmed, padded and redrawn
	across a morning; what the sizing needs is that it can be found at all.
	Padded artwork is exercised by the painted images below, which is where it
	belongs - a test that leans on the shipped file having margins fails the
	day somebody trims it, and trimming it is allowed."""
	artwork = NSImage.alloc().initByReferencingFile_(str(ARTWORK))
	assert artwork is not None and artwork.isValid(), 'the icon file is gone'
	ink = sizer.inkBounds(artwork)
	assert ink is not None and ink.size.height > 0, 'the artwork is blank'


def test_the_mark_is_the_asked_for_height(sizer):
	"""The mark, measured on the finished icon - not the canvas it sits on."""
	icon = sizer.trimmedIcon(_painted((40, 40), (5, 8, 10, 20)), 17.0)
	assert sizer.inkBounds(icon).size.height == pytest.approx(17.0, abs=0.5)


def test_the_icon_is_sized_off_the_ink_not_the_page(sizer):
	"""Same mark, twice the page, margins moved: the same icon either way."""
	tight = sizer.trimmedIcon(_painted((10, 20), (0, 0, 10, 20)), 17.0)
	padded = sizer.trimmedIcon(_painted((60, 80), (25, 30, 10, 20)), 17.0)
	assert tight.size().width == pytest.approx(padded.size().width, abs=0.5)
	assert sizer.inkBounds(tight).size.height == pytest.approx(
			sizer.inkBounds(padded).size.height, abs=0.5)


def test_the_mark_keeps_the_proportions_of_the_artwork(sizer):
	artwork = NSImage.alloc().initByReferencingFile_(str(ARTWORK))
	drawn = sizer.inkBounds(artwork)
	mark = sizer.inkBounds(sizer.trimmedIcon(artwork, Tool.TOOLBAR_ICON_HEIGHT))
	assert (mark.size.width / mark.size.height ==
			pytest.approx(drawn.size.width / drawn.size.height, rel=0.03))


def test_the_icon_fills_the_slot_glyphs_lays_out(sizer):
	"""Narrower than the slot and Glyphs hangs it off the left. See the
	comment on TOOLBAR_ICON_CANVAS."""
	icon = sizer.trimmedIcon(NSImage.alloc().initByReferencingFile_(str(ARTWORK)),
			Tool.TOOLBAR_ICON_HEIGHT)
	assert icon.size().width == pytest.approx(Tool.TOOLBAR_ICON_CANVAS)
	assert icon.size().height == pytest.approx(Tool.TOOLBAR_ICON_CANVAS)


def test_the_mark_is_centred_on_the_canvas(sizer):
	"""What the whole canvas is for: equal air on both sides, and top to bottom."""
	icon = sizer.trimmedIcon(NSImage.alloc().initByReferencingFile_(str(ARTWORK)),
			Tool.TOOLBAR_ICON_HEIGHT)
	mark, size = sizer.inkBounds(icon), icon.size()
	left = mark.origin.x
	right = size.width - (mark.origin.x + mark.size.width)
	below = mark.origin.y
	above = size.height - (mark.origin.y + mark.size.height)
	assert left == pytest.approx(right, abs=0.5), f'left {left} right {right}'
	assert below == pytest.approx(above, abs=0.5), f'below {below} above {above}'
	# and there is air to be centred in - equal margins of nothing prove nothing
	assert left > 0.5 and below > 0.5, f'no room around the mark: {left}, {below}'


def test_a_mark_taller_than_the_slot_widens_the_canvas_rather_than_cropping(sizer):
	icon = sizer.trimmedIcon(_painted((10, 10), (0, 0, 10, 10)), 40.0)
	assert icon.size().height == pytest.approx(40.0)
	assert sizer.inkBounds(icon).size.height == pytest.approx(40.0, abs=0.5)


def test_the_mark_sits_a_touch_under_the_slot(sizer):
	"""Room for the air that centres it, and 5% under the 17 that matched."""
	assert Tool.TOOLBAR_ICON_HEIGHT < Tool.TOOLBAR_ICON_CANVAS
	assert Tool.TOOLBAR_ICON_HEIGHT == pytest.approx(17.0 * 0.95, abs=0.01)


def test_the_tool_sits_at_the_end_of_the_bar(sizer):
	"""groupID: higher is further right, and the stock default is 100."""
	source = (RESOURCES / 'PKTool.py').read_text()
	assert 'self.toolbarPosition = 1000' in source


# ---------------------------------------------------------------------------
# DELETE
#
# A wall with no nodes left is not a side without a wall - it is a side that
# cannot be seen or grabbed to get one back. Both sides empty at once whenever
# the lot is selected, which is the case that used to lose the right one.
# ---------------------------------------------------------------------------

make = tool_module.makeBubbleNode
BUBBLES, NODES_L, NODES_R = (tool_module.TempDataBubblesKey,
		tool_module.TempDataLeftNodesKey, tool_module.TempDataRightNodesKey)


def _walled(width=600):
	"""A layer with a hand-drawn wall on each side, ready to be deleted from."""
	layer = Layer('n', width, paths=1)
	left = [make(x, y, 0, MASTER.xHeight) for x, y in ((40, 0), (60, 250), (40, 500))]
	right = [make(x, y, 0, MASTER.xHeight) for x, y in
			((width - 40, 0), (width - 60, 250), (width - 40, 500))]
	layer.tempData[BUBBLES] = {NODES_L: left, NODES_R: right, 'width': width}
	return layer


def _xs(layer, key):
	return [round(n.x) for n in layer.tempData[BUBBLES][key]]


def test_deleting_one_node_leaves_the_rest_alone(tool):
	layer = _walled()
	layer.selection = [layer.tempData[BUBBLES][NODES_L][1]]
	assert tool.deleteSelectedNodes(layer) is True
	assert _xs(layer, NODES_L) == [40, 40]
	assert len(layer.tempData[BUBBLES][NODES_R]) == 3


def test_emptying_the_right_side_puts_a_straight_line_back(tool):
	layer = _walled()
	layer.selection = list(layer.tempData[BUBBLES][NODES_R])
	tool.deleteSelectedNodes(layer)
	right = layer.tempData[BUBBLES][NODES_R]
	assert len(right) == 2, 'the right wall went away instead of going straight'
	assert _xs(layer, NODES_R) == [layer.width, layer.width]


def test_emptying_the_left_side_puts_a_straight_line_back(tool):
	layer = _walled()
	layer.selection = list(layer.tempData[BUBBLES][NODES_L])
	tool.deleteSelectedNodes(layer)
	assert _xs(layer, NODES_L) == [0, 0]
	assert len(layer.tempData[BUBBLES][NODES_R]) == 3, 'the other side was touched'


def test_selecting_everything_leaves_a_straight_line_on_BOTH_sides(tool):
	"""The reported bug: the left went straight and the right disappeared."""
	layer = _walled()
	layer.selection = (list(layer.tempData[BUBBLES][NODES_L])
			+ list(layer.tempData[BUBBLES][NODES_R]))
	tool.deleteSelectedNodes(layer)
	assert _xs(layer, NODES_L) == [0, 0]
	assert _xs(layer, NODES_R) == [layer.width, layer.width], \
			'the right wall was left with no nodes at all'


def test_a_layer_with_no_bubbles_is_left_alone(tool):
	layer = Layer('n', 600, paths=1)
	layer.tempData[BUBBLES] = None
	layer.selection = [object()]
	assert tool.deleteSelectedNodes(layer) is False


def test_the_lift_is_small_enough_to_still_be_a_lift():
	"""It corrects an optical centre, not a layout. Past a few per cent the
	line is not centred any more, it is high."""
	assert 0 < preview_module.OPTICAL_LIFT <= 0.08


def test_the_figures_still_clear_the_foot_once_it_is_lifted():
	"""The lift moves the line up, which is the safe direction - but the
	clamp is what says so, not the arithmetic."""
	foot = preview_module.PREVIEW_FOOT_ROOM
	for usableHeight in (120.0, 190.0, 238.0, 400.0):
		tallest = usableHeight - preview_module.KERN_LABEL_ROOM
		for lineHeight in (tallest, tallest * 0.6):
			emBottom = preview_module.previewEmBottom(usableHeight, lineHeight)
			assert preview_module.kernLabelY(emBottom) >= foot, usableHeight


# --- The canvas's own right-click menu ---------------------------------------
# Glyphs offers it to this tool whether or not the tool is the current one, so
# the PolyKern commands were turning up under a right-click in the middle of
# somebody using the Select tool.


def _menuTitles(tool):
	from AppKit import NSMenu, NSMenuItem
	menu = NSMenu.alloc().init()
	menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
		'Something Glyphs Put There', None, ''))
	tool.addMenuItemsForEvent_toMenu_(None, menu)
	return [str(menu.itemAtIndex_(i).title()) for i in range(menu.numberOfItems())]


def test_the_flag_starts_off(tool):
	"""A class default, so it reads False before activate has ever run - and
	never as a bound method, which a name AppKit also knows would give back."""
	assert tool.polyKernActive is False


def test_no_polykern_commands_while_another_tool_is_in_hand(tool):
	titles = _menuTitles(tool)
	assert titles == ['Something Glyphs Put There'], titles


def test_the_commands_are_there_while_it_is(tool, monkeypatch):
	monkeypatch.setattr(tool, 'polyKernActive', True, raising=False)
	monkeypatch.setattr(type(tool), 'setActiveLayer', lambda self: False,
			raising=False)
	titles = _menuTitles(tool)
	assert 'PolyKern Parameters…' in titles, titles


def test_leaving_the_tool_puts_the_commands_away(tool, monkeypatch):
	"""`deactivate` is the counterpart, and the declined-font path inside
	`activate` calls it too."""
	monkeypatch.setattr(tool, 'polyKernActive', True, raising=False)
	monkeypatch.setattr(tool_module.Glyphs, 'removeCallback',
			lambda *a, **k: None, raising=False)
	monkeypatch.setattr(tool_module.store, 'clearPreviewKerning',
			lambda *a, **k: None, raising=False)
	monkeypatch.setattr(type(tool), 'hideInfoBox', lambda self: None,
			raising=False)
	tool.deactivate()
	assert tool.polyKernActive is False
	assert _menuTitles(tool) == ['Something Glyphs Put There']
