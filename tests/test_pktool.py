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


def test_the_shipped_artwork_has_margins_to_lose(sizer):
	"""If this ever fails the artwork was trimmed - which is fine, but then the
	sizing below is no longer being exercised on anything."""
	artwork = NSImage.alloc().initByReferencingFile_(str(ARTWORK))
	page, ink = artwork.size(), sizer.inkBounds(artwork)
	assert ink.size.height < page.height, 'artwork already trimmed vertically'


def test_the_icon_is_the_asked_for_height(sizer):
	icon = sizer.trimmedIcon(_painted((40, 40), (5, 8, 10, 20)), 17.0)
	assert icon.size().height == pytest.approx(17.0)


def test_the_icon_is_sized_off_the_ink_not_the_page(sizer):
	"""The whole point. Same mark, twice the page: the same icon either way."""
	tight = sizer.trimmedIcon(_painted((10, 20), (0, 0, 10, 20)), 17.0)
	padded = sizer.trimmedIcon(_painted((60, 80), (25, 30, 10, 20)), 17.0)
	assert tight.size().width == pytest.approx(padded.size().width, abs=0.5)
	assert tight.size().height == pytest.approx(padded.size().height, abs=0.5)


def test_the_icon_keeps_the_proportions_of_the_mark(sizer):
	artwork = NSImage.alloc().initByReferencingFile_(str(ARTWORK))
	ink = sizer.inkBounds(artwork)
	icon = sizer.trimmedIcon(artwork, Tool.TOOLBAR_ICON_HEIGHT)
	assert (icon.size().width / icon.size().height ==
			pytest.approx(ink.size.width / ink.size.height, rel=0.02))


def test_the_finished_icon_is_all_mark(sizer):
	"""Measured again, the icon has no margin left anywhere."""
	icon = sizer.trimmedIcon(NSImage.alloc().initByReferencingFile_(str(ARTWORK)),
			Tool.TOOLBAR_ICON_HEIGHT)
	ink = sizer.inkBounds(icon)
	assert ink.size.height == pytest.approx(icon.size().height, abs=0.5)
	assert ink.size.width == pytest.approx(icon.size().width, abs=0.5)


def test_the_tool_sits_at_the_end_of_the_bar(sizer):
	"""groupID: higher is further right, and the stock default is 100."""
	source = (RESOURCES / 'PKTool.py').read_text()
	assert 'self.toolbarPosition = 1000' in source
