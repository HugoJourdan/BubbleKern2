"""A composite wears its components' bubbles.

BKCommonLogic imports GlyphsApp, so the module is loaded against a stub and
fed the smallest objects that answer the questions it asks. What is under
test is the merge, not Glyphs: which wall a layer ends up with when it is
made of components, and which one wins when it also has nodes of its own.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

RESOURCES = (pathlib.Path(__file__).parent.parent / 'BubbleKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load():
	stub = types.ModuleType('GlyphsApp')
	stub.Glyphs = types.SimpleNamespace(font=None)
	stub.GSLayer = type('GSLayer', (), {})
	stub.GSAlignmentDisable = -1
	sys.modules.setdefault('GlyphsApp', stub)
	spec = importlib.util.spec_from_file_location(
			'bk_common_logic', RESOURCES / 'BKCommonLogic.py')
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


bk = _load()

MASTER = types.SimpleNamespace(id='m1', italicAngle=0, xHeight=500, name='Regular')


class UserData(dict):
	# Glyphs hands back None for a key nobody set; a plain dict raises.
	def __missing__(self, key):
		return None


class Glyph:
	def __init__(self, name, layer):
		self.name = name
		self.layers = [layer]


class Layer:
	isMasterLayer = True

	def __init__(self, name, width, nodesL=None, nodesR=None, paths=0,
			components=()):
		self.width = width
		self.paths = [object()] * paths
		self.components = list(components)
		self.userData = UserData()
		self.tempData = {}
		if nodesL is not None:
			self.userData['BubbleKernNodesL'] = nodesL
		if nodesR is not None:
			self.userData['BubbleKernNodesR'] = nodesR
		self.parent = Glyph(name, self)

	def font(self):
		return None

	def associatedFontMaster(self):
		return MASTER


class Component:
	def __init__(self, layer, tx=0.0, ty=0.0, aligned=True, scale=1.0):
		self.componentLayer = layer
		self.transform = (scale, 0.0, 0.0, 1.0, tx, ty)
		self.alignment = 0
		self.automaticAlignment = aligned


def wall(path):
	"""Every point of a built bubble. -> [(x, y)]"""
	points = []
	for index in range(path.elementCount()):
		point = path.elementAtIndex_associatedPoints_(index)[1][0]
		points.append((round(point.x, 3), round(point.y, 3)))
	return points


@pytest.fixture
def parts():
	o = Layer('o', 600, nodesL=[(100, 0), (100, 500)], paths=2)
	accent = Layer('acc', 400, nodesL=[(0, 600), (80, 700)], paths=1)
	return o, accent


def composite(o, accent, ownNodes=None, **kwargs):
	return Layer('ocirc', 600, nodesL=ownNodes, components=[
		Component(o), Component(accent, tx=74, **kwargs)])


def test_composite_merges_its_components(parts):
	o, accent = parts
	built = wall(bk.getFinalBubble(composite(o, accent), isLeft=True))
	assert built, 'a composite of two walled components has a wall'
	# The accent reaches furthest into the whitespace, MOVED to where it sits.
	assert min(x for x, y in built) == pytest.approx(74)
	assert max(y for x, y in built) == pytest.approx(700)


def test_own_nodes_replace_the_merge(parts):
	o, accent = parts
	built = wall(bk.getFinalBubble(
			composite(o, accent, ownNodes=[(200, 0), (200, 700)]), isLeft=True))
	# Drawn beats inherited, INWARD AS WELL AS OUT: a union would have kept
	# the components' 74 and the hand-drawn wall would not have moved.
	assert built and all(x == pytest.approx(200) for x, y in built)


def test_the_default_line_does_not_replace_it(parts):
	o, accent = parts
	built = wall(bk.getFinalBubble(
			composite(o, accent, ownNodes=[(0, 0), (0, 700)]), isLeft=True))
	assert min(x for x, y in built) == pytest.approx(74)


def test_mergeable_composite(parts):
	o, accent = parts
	assert bk.mergeableComposite(composite(o, accent))
	assert not bk.mergeableComposite(composite(o, accent, aligned=False))
	assert not bk.mergeableComposite(composite(o, accent, scale=-1.0))
	assert not bk.mergeableComposite(o)  # draws its own outline


# --- o, circumflexcomb, ocircumflex ----------------------------------------
# THE NUMBERS ARE THE FONT'S OWN, read out of the Medium master of AZ Grotesk
# with the plugin's own getFinalBubble. A merge that cannot reproduce the one
# glyph it was written for is not worth much.

O_WIDTH, ACCENT_WIDTH = 600, 454
ACCENT_DX = 74  # where the circumflex sits over the o
O_L = [(114, -16), (30, 98), (8, 168), (0, 252), (7, 338), (29, 408), (115, 524)]
O_R = [(-114, -16), (-30, 98), (-8, 168), (0, 252), (-7, 338), (-29, 408),
		(-115, 524)]
ACCENT_L = [(7, 571), (121, 700)]
ACCENT_R = [(0, 572), (-83, 700)]


class Node:
	# WHAT tempData HOLDS: objects with .x and .y, not tuples.
	def __init__(self, x, y):
		self.x, self.y = float(x), float(y)


@pytest.fixture
def oh():
	"""o, circumflexcomb and the ocircumflex made of them."""
	o = Layer('o', O_WIDTH, nodesL=O_L, nodesR=O_R, paths=2)
	accent = Layer('circumflexcomb', ACCENT_WIDTH, nodesL=ACCENT_L,
			nodesR=ACCENT_R, paths=1)
	ocirc = Layer('ocircumflex', O_WIDTH, components=[
			Component(o), Component(accent, tx=ACCENT_DX)])
	return o, accent, ocirc


def test_the_left_wall_of_ocircumflex_is_its_two_components(oh):
	o, accent, ocirc = oh
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	# The o's wall as drawn, then the accent's MOVED to where the accent sits.
	assert built[:7] == [(float(x), float(y)) for x, y in O_L]
	assert built[7:] == [(7.0 + ACCENT_DX, 571.0), (121.0 + ACCENT_DX, 700.0)]


def test_the_right_wall_is_placed_against_each_layers_own_advance(oh):
	o, accent, ocirc = oh
	built = wall(bk.getFinalBubble(ocirc, isLeft=False))
	# The o's wall against the o's 600; the accent's against ITS OWN 454 and
	# then moved by 74 - not against the 600 of the glyph being built.
	assert built[:7] == [(x + O_WIDTH, float(y)) for x, y in O_R]
	assert built[7:] == [(0.0 + ACCENT_WIDTH + ACCENT_DX, 572.0),
			(-83.0 + ACCENT_WIDTH + ACCENT_DX, 700.0)]


def test_a_composites_own_cache_is_not_a_wall_of_its_own(oh):
	"""tempData on a composite holds the wall it RESOLVES to, put there so the
	handles have something to sit on. Reading it back as if the composite had
	drawn it merges the answer with itself."""
	o, accent, ocirc = oh
	ocirc.tempData['bubbles'] = {'nodesL': [Node(23, 571), Node(155, 700)]}
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	assert (23.0, 571.0) not in built, 'the cache is not a third component'
	assert built[7:] == [(81.0, 571.0), (195.0, 700.0)]


def test_a_stale_cache_cannot_ratchet_the_wall_outward(oh):
	"""The symptom that made an edit to the accent invisible: last time round
	the wall reached x=23, and the merge kept reading its own answer, so the
	accent could be pushed out but never pulled back in."""
	o, accent, ocirc = oh
	ocirc.tempData['bubbles'] = {'nodesL': [Node(23, 571), Node(155, 700)]}
	accent.userData['BubbleKernNodesL'] = [(60, 571), (180, 700)]  # pulled IN
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	assert min(x for x, y in built if y >= 571) == pytest.approx(134)


def test_a_component_with_no_wall_of_its_own_says_nothing(oh):
	"""The default line on the origin is not a wall, and it is not one when a
	component carries it either: moved onto the composite it becomes a wall
	standing at the component's origin - outside the glyph when the component
	is moved left - and the union keeps whatever reaches furthest out."""
	o, accent, ocirc = oh
	accent.userData['BubbleKernNodesL'] = [(0, 544), (0, 650)]
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	assert built == [(float(x), float(y)) for x, y in O_L]


def test_a_component_moved_left_cannot_push_the_wall_past_the_origin(oh):
	"""`ocircumflex` in a master where nobody has drawn a bubble yet: every
	wall is the default line, and the accent's is moved 52 units left of the
	origin. A left wall outside the glyph pushes everything away from it."""
	o, accent, ocirc = oh
	o.userData['BubbleKernNodesL'] = [(0, -6), (0, 506)]
	accent.userData['BubbleKernNodesL'] = [(0, 544), (0, 650)]
	ocirc.components[1].transform = (1.0, 0.0, 0.0, 1.0, -52.0, 0.0)
	ocirc.userData['BubbleKernNodesL'] = [(0, -6), (0, 650)]
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	assert min(x for x, y in built) == pytest.approx(0), built


def test_a_component_with_no_bubble_at_all_is_skipped(oh):
	"""gatherBubbleInfo answers None for a layer with nothing to give. Kept in
	the list it is a child with no transform to read."""
	o, accent, ocirc = oh
	del o.userData['BubbleKernNodesL']
	built = wall(bk.getFinalBubble(ocirc, isLeft=True))
	assert built == [(81.0, 571.0), (195.0, 700.0)]


def test_a_merged_composite_is_never_asked_to_draw_one(oh):
	"""`auto` on a composite clears its nodes and hands it to its components.
	Staleness must not ask for them straight back, or the wall is stamped on
	again on the next interface update and the merge is over."""
	o, accent, ocirc = oh
	ocirc.userData['BubbleKernAutoL'] = 1
	assert not bk.needsGenerating(ocirc, True)
	# A GLYPH THAT DRAWS ITS OWN INK still gets one: nothing to borrow.
	o.userData['BubbleKernAutoL'] = 1
	del o.userData['BubbleKernNodesL']
	assert bk.needsGenerating(o, True)


# --- A side that mirrors the other one -------------------------------------


def mirrorTheAccent(accent):
	# `=|` STORES NOTHING BUT THE FLAG, so the nodes go.
	del accent.userData['BubbleKernNodesR']
	accent.userData['BubbleKernMirrorR'] = 1


def test_a_mirrored_side_is_the_other_one_flipped(oh):
	o, accent, ocirc = oh
	mirrorTheAccent(accent)
	built = wall(bk.getFinalBubble(accent, isLeft=False))
	assert built == [(ACCENT_WIDTH - 7.0, 571.0), (ACCENT_WIDTH - 121.0, 700.0)]


def test_a_mirrored_side_on_a_component_still_reaches_the_composite(oh):
	"""`circumflexcomb` with `=|` on its right. The flag is all that is stored
	- the shape is resolved from the other side every time - and only
	getFinalBubble knew that, so a composite reading its components for nodes
	found none and the accent handed `ocircumflex` nothing."""
	o, accent, ocirc = oh
	mirrorTheAccent(accent)
	built = wall(bk.getFinalBubble(ocirc, isLeft=False))
	above = [(x, y) for x, y in built if y > 524]
	assert above, 'the accent is part of the wall'
	# Its left wall flipped about its OWN advance, then moved to where it sits.
	assert max(x for x, y in above) == pytest.approx(ACCENT_WIDTH - 7 + ACCENT_DX)
