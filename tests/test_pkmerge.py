"""A composite wears its components' bubbles.

PKCommonLogic imports GlyphsApp, so the module is loaded against a stub and
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

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load():
	stub = types.ModuleType('GlyphsApp')
	stub.Glyphs = types.SimpleNamespace(font=None)
	stub.GSLayer = type('GSLayer', (), {})
	stub.GSAlignmentDisable = -1
	sys.modules.setdefault('GlyphsApp', stub)
	spec = importlib.util.spec_from_file_location(
			'pk_common_logic', RESOURCES / 'PKCommonLogic.py')
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


pk = _load()

MASTER = types.SimpleNamespace(id='m1', italicAngle=0, xHeight=500, name='Regular')


class UserData(dict):
	# Glyphs hands back None for a key nobody set; a plain dict raises.
	def __missing__(self, key):
		return None


class Layers(list):
	# Glyphs indexes a glyph's layers by master id as well as by position, and
	# a reference is resolved that way: `font.glyphs[name].layers[masterId]`.
	def __getitem__(self, key):
		if isinstance(key, str):
			return next((l for l in self if l.associatedMasterId == key), None)
		return list.__getitem__(self, key)


class Glyph:
	def __init__(self, name, layer):
		self.name = name
		self.layers = Layers([layer])


class Font:
	"""Enough font for a reference to be resolved through. Attaches itself to
	the layers it is given, which is how `layer.font()` finds it."""

	def __init__(self, *layers):
		self.glyphs = UserData(
				(layer.parent.name, layer.parent) for layer in layers)
		for layer in layers:
			layer.owner = self


class Layer:
	isMasterLayer = True
	associatedMasterId = MASTER.id
	owner = None

	def __init__(self, name, width, nodesL=None, nodesR=None, paths=0,
			components=()):
		self.width = width
		self.paths = [object()] * paths
		self.components = list(components)
		self.userData = UserData()
		self.tempData = {}
		if nodesL is not None:
			self.userData['PolyKernNodesL'] = nodesL
		if nodesR is not None:
			self.userData['PolyKernNodesR'] = nodesR
		self.parent = Glyph(name, self)

	def font(self):
		return self.owner

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
	built = wall(pk.getFinalBubble(composite(o, accent), isLeft=True))
	assert built, 'a composite of two walled components has a wall'
	# The accent reaches furthest into the whitespace, MOVED to where it sits.
	assert min(x for x, y in built) == pytest.approx(74)
	assert max(y for x, y in built) == pytest.approx(700)


def test_own_nodes_replace_the_merge(parts):
	o, accent = parts
	built = wall(pk.getFinalBubble(
			composite(o, accent, ownNodes=[(200, 0), (200, 700)]), isLeft=True))
	# Drawn beats inherited, INWARD AS WELL AS OUT: a union would have kept
	# the components' 74 and the hand-drawn wall would not have moved.
	assert built and all(x == pytest.approx(200) for x, y in built)


def test_the_default_line_does_not_replace_it(parts):
	o, accent = parts
	built = wall(pk.getFinalBubble(
			composite(o, accent, ownNodes=[(0, 0), (0, 700)]), isLeft=True))
	assert min(x for x, y in built) == pytest.approx(74)


def test_mergeable_composite(parts):
	o, accent = parts
	assert pk.mergeableComposite(composite(o, accent))
	assert not pk.mergeableComposite(composite(o, accent, aligned=False))
	assert not pk.mergeableComposite(composite(o, accent, scale=-1.0))
	assert not pk.mergeableComposite(o)  # draws its own outline


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
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	# The o's wall as drawn, then the accent's MOVED to where the accent sits.
	assert built[:7] == [(float(x), float(y)) for x, y in O_L]
	assert built[7:] == [(7.0 + ACCENT_DX, 571.0), (121.0 + ACCENT_DX, 700.0)]


def test_the_right_wall_is_placed_against_each_layers_own_advance(oh):
	o, accent, ocirc = oh
	built = wall(pk.getFinalBubble(ocirc, isLeft=False))
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
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	assert (23.0, 571.0) not in built, 'the cache is not a third component'
	assert built[7:] == [(81.0, 571.0), (195.0, 700.0)]


def test_a_stale_cache_cannot_ratchet_the_wall_outward(oh):
	"""The symptom that made an edit to the accent invisible: last time round
	the wall reached x=23, and the merge kept reading its own answer, so the
	accent could be pushed out but never pulled back in."""
	o, accent, ocirc = oh
	ocirc.tempData['bubbles'] = {'nodesL': [Node(23, 571), Node(155, 700)]}
	accent.userData['PolyKernNodesL'] = [(60, 571), (180, 700)]  # pulled IN
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	assert min(x for x, y in built if y >= 571) == pytest.approx(134)


def test_a_component_with_no_wall_of_its_own_says_nothing(oh):
	"""The default line on the origin is not a wall, and it is not one when a
	component carries it either: moved onto the composite it becomes a wall
	standing at the component's origin - outside the glyph when the component
	is moved left - and the union keeps whatever reaches furthest out."""
	o, accent, ocirc = oh
	accent.userData['PolyKernNodesL'] = [(0, 544), (0, 650)]
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	assert built == [(float(x), float(y)) for x, y in O_L]


def test_a_component_moved_left_cannot_push_the_wall_past_the_origin(oh):
	"""`ocircumflex` in a master where nobody has drawn a bubble yet: every
	wall is the default line, and the accent's is moved 52 units left of the
	origin. A left wall outside the glyph pushes everything away from it."""
	o, accent, ocirc = oh
	o.userData['PolyKernNodesL'] = [(0, -6), (0, 506)]
	accent.userData['PolyKernNodesL'] = [(0, 544), (0, 650)]
	ocirc.components[1].transform = (1.0, 0.0, 0.0, 1.0, -52.0, 0.0)
	ocirc.userData['PolyKernNodesL'] = [(0, -6), (0, 650)]
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	assert min(x for x, y in built) == pytest.approx(0), built


def test_a_component_with_no_bubble_at_all_is_skipped(oh):
	"""gatherBubbleInfo answers None for a layer with nothing to give. Kept in
	the list it is a child with no transform to read."""
	o, accent, ocirc = oh
	del o.userData['PolyKernNodesL']
	built = wall(pk.getFinalBubble(ocirc, isLeft=True))
	assert built == [(81.0, 571.0), (195.0, 700.0)]


def test_a_merged_composite_is_never_asked_to_draw_one(oh):
	"""`auto` on a composite clears its nodes and hands it to its components.
	Staleness must not ask for them straight back, or the wall is stamped on
	again on the next interface update and the merge is over."""
	o, accent, ocirc = oh
	ocirc.userData['PolyKernAutoL'] = 1
	assert not pk.needsGenerating(ocirc, True)
	# A GLYPH THAT DRAWS ITS OWN INK still gets one: nothing to borrow.
	o.userData['PolyKernAutoL'] = 1
	del o.userData['PolyKernNodesL']
	assert pk.needsGenerating(o, True)


# --- A side that mirrors the other one -------------------------------------


def mirrorTheAccent(accent):
	# `=|` STORES NOTHING BUT THE FLAG, so the nodes go.
	del accent.userData['PolyKernNodesR']
	accent.userData['PolyKernMirrorR'] = 1


def test_a_mirrored_side_is_the_other_one_flipped(oh):
	o, accent, ocirc = oh
	mirrorTheAccent(accent)
	built = wall(pk.getFinalBubble(accent, isLeft=False))
	assert built == [(ACCENT_WIDTH - 7.0, 571.0), (ACCENT_WIDTH - 121.0, 700.0)]


def test_a_mirrored_side_on_a_component_still_reaches_the_composite(oh):
	"""`circumflexcomb` with `=|` on its right. The flag is all that is stored
	- the shape is resolved from the other side every time - and only
	getFinalBubble knew that, so a composite reading its components for nodes
	found none and the accent handed `ocircumflex` nothing."""
	o, accent, ocirc = oh
	mirrorTheAccent(accent)
	built = wall(pk.getFinalBubble(ocirc, isLeft=False))
	above = [(x, y) for x, y in built if y > 524]
	assert above, 'the accent is part of the wall'
	# Its left wall flipped about its OWN advance, then moved to where it sits.
	assert max(x for x, y in above) == pytest.approx(ACCENT_WIDTH - 7 + ACCENT_DX)


# --- A borrowed wall sits on the glyph borrowing it --------------------------
# `m` pointing its right side at `n` is not an `n` sitting somewhere inside
# `m`: there is no transform saying where the wall goes, the way a component
# carries one. Read against the lender's advance, a borrowed right wall stands
# that much inside the borrower.


def _pointedAt(borrower, lender, isLeft=False):
	borrower.userData['PolyKernRefer' + ('L' if isLeft else 'R')] = \
			lender.parent.name
	Font(borrower, lender)
	return borrower


def test_a_borrowed_right_wall_moves_out_to_the_borrowers_advance():
	"""`m` wearing `n`'s right side, and `m` is 300 units the wider."""
	n = Layer('n', 600, nodesR=[(-90, 0), (-90, 500)], paths=1)
	m = Layer('m', 900, paths=1)
	built = wall(pk.getFinalBubble(_pointedAt(m, n), isLeft=False))
	assert built, 'no wall at all'
	# 90 in from 900, not 90 in from 600 - which is the middle of the last stem.
	assert all(x == pytest.approx(810) for x, y in built), built


def test_a_borrowed_left_wall_stays_where_it_was_drawn():
	"""The left is measured from an origin the two of them share, so there is
	nothing to move it by - and moving it would break every `n`/`m` pair that
	borrows the side they genuinely have in common."""
	n = Layer('n', 600, nodesL=[(90, 0), (90, 500)], paths=1)
	m = Layer('m', 900, paths=1)
	built = wall(pk.getFinalBubble(_pointedAt(m, n, isLeft=True), isLeft=True))
	assert built and all(x == pytest.approx(90) for x, y in built), built


# --- A side that mirrors ANOTHER glyph's ------------------------------------
# `=|A`, which is Glyphs' own metric key for the other side of another glyph.
# The wall is flipped about the advance of whoever DREW it and then moved onto
# the glyph wearing it, and those two do not commute.


def _mirroring(borrower, lender, isLeft=True):
	borrower.userData['PolyKernMirror' + ('L' if isLeft else 'R')] = \
			lender.parent.name
	Font(borrower, lender)
	return borrower


def test_a_mirrored_left_side_is_the_lenders_right_flipped():
	"""`d` left set to `=|b`: 90 in from b's advance becomes 90 out from d's
	origin, whatever the two advances are."""
	b = Layer('b', 600, nodesR=[(-90, 0), (-90, 500)], paths=1)
	d = Layer('d', 900, paths=1)
	built = wall(pk.getFinalBubble(_mirroring(d, b), isLeft=True))
	assert built and all(x == pytest.approx(90) for x, y in built), built


def test_a_mirrored_right_side_lands_against_the_borrowers_advance():
	"""The other way round, and the difference of the advances is the move:
	flipped about the lender's 600 the wall sits at 510, and 510 is 90 inside
	the LENDER - the middle of the borrower."""
	q = Layer('q', 600, nodesL=[(90, 0), (90, 500)], paths=1)
	p = Layer('p', 900, paths=1)
	built = wall(pk.getFinalBubble(_mirroring(p, q, isLeft=False), isLeft=False))
	assert built and all(x == pytest.approx(810) for x, y in built), built


def test_a_mirror_of_a_glyph_that_is_not_there_says_nothing():
	d = Layer('d', 900, paths=1)
	d.userData['PolyKernMirrorL'] = 'nosuchglyph'
	Font(d)
	assert pk.gatherBubbleInfo(d, isLeft=True) is None


def test_two_glyphs_mirroring_each_other_are_a_ring():
	"""`d` left from `b` right, `b` right from `d` left: nothing at either end
	of it, and followed it recurses until Python gives up."""
	b = Layer('b', 600, paths=1)
	d = Layer('d', 600, paths=1)
	Font(b, d)
	d.userData['PolyKernMirrorL'] = 'b'
	b.userData['PolyKernMirrorR'] = 'd'
	assert pk.gatherBubbleInfo(d, isLeft=True) is None
