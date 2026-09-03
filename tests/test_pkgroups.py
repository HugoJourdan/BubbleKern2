# encoding: utf-8
"""Which glyphs really do share a fingerprint.

A REFERENCE IS THE ONLY PLACE TWO GLYPHS SHARE ONE. Two walls that came out the
same shape are still two walls and drift apart the moment either glyph is
touched; a Refer glyph is one wall read from two places. So the Groups pane
reads the references, and what is pinned here is that it reads ALL of them -
whoever wrote them - that a chain lands on the glyph at its end, and that the
things that are not groups (a glyph on its own, a circle, a dead name) do not
turn up as one.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name, as_name=None):
	key = as_name or ('pk_' + name)
	if key in sys.modules:
		return sys.modules[key]
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location(key, RESOURCES / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	sys.modules[key] = module
	spec.loader.exec_module(module)
	return module


store = _load('PKBubbleStore', 'PKBubbleStore')
sys.modules.setdefault('PKTool', types.SimpleNamespace(mainDrawingHandler=None))
kerner = _load('PKKerner')

LEFT, RIGHT = store.LEFT, store.RIGHT
MASTER = 'm1'


class UserData(dict):
	def __missing__(self, key):
		return None


class Layers(dict):
	def __missing__(self, key):
		return None  # Glyphs answers None for a master it has no layer for


class Layer:
	def __init__(self, glyph, font, **userData):
		self.parent = glyph
		self.userData = UserData(userData)
		self.associatedMasterId = MASTER
		self._font = font

	def font(self):
		return self._font


class Glyph:
	def __init__(self, name):
		self.name = name
		self.layers = Layers()


class Font:
	"""`font.glyphs` both iterates and answers to a name, as in Glyphs."""

	def __init__(self):
		self._byName = {}
		self.glyphs = self

	def __iter__(self):
		return iter(list(self._byName.values()))

	def __getitem__(self, name):
		return self._byName.get(name)

	def add(self, name, **userData):
		glyph = Glyph(name)
		glyph.layers[MASTER] = Layer(glyph, self, **userData)
		self._byName[name] = glyph
		return glyph


def _font(*specs):
	"""_font(('c', RIGHT, 'o'), ('o', None, None)) -> a font wired like that."""
	font = Font()
	for name, side, target in specs:
		data = {side.key('Refer'): target} if side is not None else {}
		font.add(name, **data)
	return font


def _named(groups, name, side):
	for group in groups:
		if group['name'] == name and group['side'] is side:
			return group
	return None


# --- What is a group --------------------------------------------------------


def test_the_glyphs_pointing_at_one_glyph_are_its_group():
	font = _font(('o', None, None), ('c', RIGHT, 'o'), ('e', RIGHT, 'o'))
	groups = store.referGroups(font, MASTER)
	assert len(groups) == 1
	assert groups[0]['name'] == 'o' and groups[0]['side'] is RIGHT
	assert groups[0]['members'] == ['o', 'c', 'e']


def test_the_glyph_they_borrow_from_comes_first():
	"""It is the one carrying the drawing, and the grid draws cell one biggest
	in the reader's mind whatever it does on screen."""
	font = _font(('o', None, None), ('a', RIGHT, 'o'), ('z', RIGHT, 'o'))
	members = store.referGroups(font, MASTER)[0]['members']
	assert members[0] == 'o', members
	assert members[1:] == ['a', 'z'], 'the rest are not in order'


def test_a_glyph_on_its_own_is_not_a_group():
	font = _font(('o', None, None), ('n', None, None))
	assert store.referGroups(font, MASTER) == []


def test_the_two_sides_are_two_groups():
	"""A glyph borrows its left wall from one glyph and its right from
	another, and neither says anything about the other."""
	font = Font()
	font.add('o')
	font.add('n')
	font.add('b', **{LEFT.key('Refer'): 'n', RIGHT.key('Refer'): 'o'})
	groups = store.referGroups(font, MASTER)
	assert len(groups) == 2
	assert _named(groups, 'n', LEFT)['members'] == ['n', 'b']
	assert _named(groups, 'o', RIGHT)['members'] == ['o', 'b']


def test_a_chain_lands_on_the_glyph_at_its_end():
	"""a -> b -> c is one group of three around c, not two of two: the wall
	every one of them draws is c's."""
	font = _font(('c', None, None), ('b', RIGHT, 'c'), ('a', RIGHT, 'b'))
	groups = store.referGroups(font, MASTER)
	assert len(groups) == 1
	assert groups[0]['name'] == 'c'
	assert sorted(groups[0]['members']) == ['a', 'b', 'c']


def test_a_circle_is_not_a_group():
	"""Nothing in it carries a wall, so there is nothing to show."""
	font = _font(('a', RIGHT, 'b'), ('b', RIGHT, 'a'))
	assert store.referGroups(font, MASTER) == []


def test_a_reference_to_a_glyph_that_is_gone_is_not_a_group():
	font = _font(('a', RIGHT, 'deleted'))
	assert store.referGroups(font, MASTER) == []


def test_the_biggest_group_comes_first():
	font = Font()
	font.add('o')
	font.add('n')
	for name in ('c', 'e', 'd'):
		font.add(name, **{RIGHT.key('Refer'): 'o'})
	font.add('m', **{RIGHT.key('Refer'): 'n'})
	sizes = [len(group['members']) for group in store.referGroups(font, MASTER)]
	assert sizes == sorted(sizes, reverse=True), sizes
	assert sizes[0] == 4


def test_a_master_with_no_layers_gives_nothing_rather_than_raising():
	font = _font(('o', None, None), ('c', RIGHT, 'o'))
	assert store.referGroups(font, 'nosuchmaster') == []


def test_one_side_can_be_asked_for_on_its_own():
	font = Font()
	font.add('o')
	font.add('n')
	font.add('b', **{LEFT.key('Refer'): 'n', RIGHT.key('Refer'): 'o'})
	groups = store.referGroups(font, MASTER, sides=(RIGHT,))
	assert [group['side'] for group in groups] == [RIGHT]


# --- What the pane says about them ------------------------------------------


def test_an_empty_font_is_told_what_to_do_about_it():
	said = kerner.PolyKernKerner.groupsCaption(None, [])
	assert 'PolyKern Group' in said and 'Automatically' in said


def test_the_caption_counts_the_bands_and_the_glyphs():
	said = kerner.PolyKernKerner.groupsCaption(None,
			[{'name': 'o', 'members': ['o', 'c', 'e']}])
	assert said.startswith('1 group, 3 glyphs'), said
