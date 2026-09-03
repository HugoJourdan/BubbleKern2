# encoding: utf-8
"""Clearing PolyKern's data off the selected glyphs.

The menu item is the point, but the clearing under it is shared with the
whole-font Remove button, which used to name its keys by hand and so walked
past `Mirror`, `Box` and `Auto`. What is pinned here is that a cleared side is
clear of ALL SIX concepts, that the cache the canvas draws from goes with them,
and that the question is asked before anything is taken away.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name, as_name=None):
	# ONCE PER SESSION, WHOEVER ASKS FIRST. Executing a module twice re-registers
	# the ObjC classes in it - `escapableSheet` in PKKerner, `BubbleNode` in
	# PKTool - and objc refuses the second one.
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

from GlyphsApp import Glyphs, GSLayer  # the conftest stub

LEFT, RIGHT, CONCEPTS = store.LEFT, store.RIGHT, store.CONCEPTS
M1 = type('Master', (), {'id': 'm1', 'name': 'Regular', 'italicAngle': 0,
		'xHeight': 500, 'ascender': 750, 'descender': -250})()
M2 = type('Master', (), {'id': 'm2', 'name': 'Bold', 'italicAngle': 0,
		'xHeight': 500, 'ascender': 750, 'descender': -250})()
DRAWN = [(100, 0), (100, 500)]


class UserData(dict):
	def __missing__(self, key):
		return None


class Glyph:
	def __init__(self, name):
		self.name = name
		self.layers = {}
		self.undo = 0
		self.deepest = 0

	def beginUndo(self):
		self.undo += 1
		self.deepest = max(self.deepest, self.undo)

	def endUndo(self):
		self.undo -= 1


class Layer(GSLayer):
	isMasterLayer = True

	def __init__(self, name='a', master=M1, glyph=None, **userData):
		self.width = 600
		self.paths = [object()]
		self.components = []
		self.userData = UserData(userData)
		self.tempData = UserData()
		self.name = master.name
		self.master = master
		self.parent = glyph or Glyph(name)
		self.parent.layers[master.id] = self

	def associatedFontMaster(self):
		return self.master


def _full(**extra):
	"""A layer with every concept set on the left side."""
	data = {LEFT.key(concept): value for concept, value in zip(
			CONCEPTS, ([(1, 2)], 'o', True, [0, 0, 100, 100, 600], 1, True))}
	data.update(extra)
	return Layer(**data)


# --- What a clear takes away ------------------------------------------------


def test_clearing_a_side_takes_all_six_concepts():
	layer = _full()
	assert store.clearSide(layer, LEFT) is True
	left = [c for c in CONCEPTS if layer.userData[LEFT.key(c)] is not None]
	assert left == [], f'left behind: {left}'


def test_clearing_a_side_leaves_the_other_alone():
	layer = _full(**{RIGHT.key('Nodes'): DRAWN})
	store.clearSide(layer, LEFT)
	assert layer.userData[RIGHT.key('Nodes')] == DRAWN


def test_clearing_nothing_says_so():
	assert store.clearSide(Layer(), LEFT) is False


def test_an_auto_side_is_carried_even_though_it_is_not_work():
	"""The deliberate difference from `holdsWork`: a generate run is happy to
	redo an auto side, but a clear still has to take the flag off."""
	layer = Layer(**{LEFT.key('Auto'): 1})
	assert store.holdsWork(layer, LEFT) is False
	assert store.carriesAnything(layer, LEFT) is True


def test_the_count_covers_both_sides_of_every_layer():
	layers = [Layer(**{LEFT.key('Nodes'): DRAWN, RIGHT.key('Nodes'): DRAWN}),
			Layer(**{LEFT.key('Mirror'): True}), Layer()]
	assert store.countCarried(layers) == 3


def test_clearing_reports_how_many_sides_went():
	layers = [Layer(**{LEFT.key('Nodes'): DRAWN, RIGHT.key('Nodes'): DRAWN}),
			Layer(**{LEFT.key('Refer'): 'o'}), Layer()]
	assert store.clearBubbles(layers) == 3


def test_the_drawn_cache_goes_with_it():
	"""tempData is what the canvas draws from, so a side cleared only in
	userData is still on screen."""
	layer = _full()
	layer.tempData['bubbles'] = {'nodesL': [object()], 'width': 600}
	store.clearBubbles([layer])
	assert layer.tempData['bubbles'] is None


def test_a_layer_with_no_cache_is_no_trouble():
	layer = _full()
	assert store.clearBubbles([layer]) == 1


def test_each_layer_is_one_undo_step():
	glyph = Glyph('a')
	layers = [Layer('a', M1, glyph, **{LEFT.key('Nodes'): DRAWN}),
			Layer('a', M2, glyph, **{LEFT.key('Nodes'): DRAWN})]
	store.clearBubbles(layers)
	assert glyph.undo == 0, 'an undo group was left open'
	assert glyph.deepest == 1, 'the groups nested instead of closing'


# --- The menu item ----------------------------------------------------------


@pytest.fixture
def run(monkeypatch):
	"""Drive `clearSides` with a canned answer. -> (asked, alerted, layers)"""
	def go(layers, answer, allMasters=False, masters=(M1,)):
		asked, alerted = [], []
		font = types.SimpleNamespace(masters=list(masters),
				selectedFontMaster=M1, selectedLayers=layers)
		monkeypatch.setattr(Glyphs, 'font', font, raising=False)
		monkeypatch.setattr(kerner.PKCommonLogic, 'ask_choice',
				lambda title, body, buttons: asked.append(title) or answer)
		monkeypatch.setattr(kerner.PKCommonLogic, 'show_alert',
				lambda *a, **k: alerted.append(a[0]))
		plugin = kerner.PolyKernKerner.__new__(kerner.PolyKernKerner)
		plugin.clearSides(allMasters)
		return asked, alerted
	return go


CLEAR, CANCEL = 1, 0


def test_cancelling_takes_nothing_away(run):
	layer = Layer(**{LEFT.key('Nodes'): DRAWN})
	asked, _ = run([layer], CANCEL)
	assert len(asked) == 1, 'it did not ask'
	assert layer.userData[LEFT.key('Nodes')] == DRAWN


def test_confirming_clears(run):
	layer = Layer(**{LEFT.key('Nodes'): DRAWN, RIGHT.key('Refer'): 'o'})
	run([layer], CLEAR)
	assert layer.userData[LEFT.key('Nodes')] is None
	assert layer.userData[RIGHT.key('Refer')] is None


def test_the_question_carries_the_number_of_sides(run):
	layers = [Layer('a', **{LEFT.key('Nodes'): DRAWN, RIGHT.key('Nodes'): DRAWN}),
			Layer('b', **{LEFT.key('Auto'): 1})]
	asked, _ = run(layers, CANCEL)
	assert '3' in asked[0], asked[0]


def test_nothing_to_clear_is_said_not_asked(run):
	asked, alerted = run([Layer()], CLEAR)
	assert asked == [], 'asked about nothing'
	assert alerted == ['Nothing to Clear']


def test_option_reaches_every_master(run):
	glyph = Glyph('a')
	here = Layer('a', M1, glyph, **{LEFT.key('Nodes'): DRAWN})
	there = Layer('a', M2, glyph, **{LEFT.key('Nodes'): DRAWN})
	run([here], CLEAR, allMasters=True, masters=(M1, M2))
	assert here.userData[LEFT.key('Nodes')] is None
	assert there.userData[LEFT.key('Nodes')] is None, 'the other master was left'


def test_without_option_only_the_current_master(run):
	glyph = Glyph('a')
	here = Layer('a', M1, glyph, **{LEFT.key('Nodes'): DRAWN})
	there = Layer('a', M2, glyph, **{LEFT.key('Nodes'): DRAWN})
	run([here], CLEAR, allMasters=False, masters=(M1, M2))
	assert here.userData[LEFT.key('Nodes')] is None
	assert there.userData[LEFT.key('Nodes')] == DRAWN, 'it reached another master'
