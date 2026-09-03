# encoding: utf-8
"""Asking before a generate run writes over somebody's work.

The Edit menu's generate item used to write both walls of every selected layer
without a word, and `writeBubble` clears a reference and a mirror flag as it
goes - so a side borrowed from another glyph was gone with the same silence as
one drawn by hand. Two things are pinned here: WHAT COUNTS as work to lose,
and what the run does with each of the three answers.
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


# Under its plain name, so the `import PKBubbleStore` inside `generateBubbles`
# finds this very object and the monkeypatching below reaches it.
store = _load('PKBubbleStore', 'PKBubbleStore')
# STUBBED, NEVER LOADED: `generateBubbles` only asks the tool whether there is
# a canvas to redraw, and executing PKTool.py twice under two names re-registers
# its ObjC classes.
sys.modules.setdefault('PKTool', types.SimpleNamespace(mainDrawingHandler=None))
kerner = _load('PKKerner')

from GlyphsApp import Glyphs, GSLayer  # the conftest stub

LEFT, RIGHT = store.LEFT, store.RIGHT
MASTER = type('Master', (), {'id': 'm1', 'italicAngle': 0, 'xHeight': 500,
		'name': 'Regular', 'ascender': 750, 'descender': -250})()


class UserData(dict):
	def __missing__(self, key):
		return None


class Glyph:
	def __init__(self, name):
		self.name = name
		self.layers = {}

	def beginUndo(self):
		pass

	def endUndo(self):
		pass


class Layer(GSLayer):
	isMasterLayer = True

	def __init__(self, name='a', **userData):
		self.width = 600
		self.paths = [object()]
		self.components = []
		self.userData = UserData(userData)
		self.tempData = UserData()
		self.name = 'Regular'
		self.parent = Glyph(name)
		self.parent.layers['m1'] = self

	def associatedFontMaster(self):
		return MASTER


DRAWN = [(100, 0), (100, 500)]
BLANK = [(0, 0), (0, 700)]


# --- What counts as work to lose --------------------------------------------


def test_a_hand_drawn_wall_counts():
	assert store.holdsWork(Layer(PolyKernNodesL=DRAWN), LEFT) is True


def test_a_borrowed_side_counts():
	# `writeBubble` deletes the reference, so a run does destroy it.
	assert store.holdsWork(Layer(PolyKernReferL='o'), LEFT) is True


def test_a_mirrored_side_counts():
	assert store.holdsWork(Layer(PolyKernMirrorL=True), LEFT) is True


def test_an_auto_side_does_not():
	# It asked to be kept up to date; regenerating is the thing it is for.
	layer = Layer(PolyKernAutoL=1, PolyKernNodesL=DRAWN)
	assert store.holdsWork(layer, LEFT) is False


def test_the_blank_line_on_the_origin_does_not():
	# What every layer carries when nobody has drawn it anything.
	assert store.holdsWork(Layer(PolyKernNodesL=BLANK), LEFT) is False


def test_an_empty_side_does_not():
	assert store.holdsWork(Layer(), LEFT) is False


def test_a_side_is_asked_about_on_its_own_side_only():
	layer = Layer(PolyKernNodesL=DRAWN)
	assert store.holdsWork(layer, LEFT) is True
	assert store.holdsWork(layer, RIGHT) is False


def test_both_sides_mirroring_each_other_is_neither():
	# `isMirrored` calls that meaningless, and so must this.
	layer = Layer(PolyKernMirrorL=True, PolyKernMirrorR=True)
	assert store.holdsWork(layer, LEFT) is False


# --- The count ---------------------------------------------------------------


def test_the_count_covers_both_sides_of_every_layer():
	layers = [Layer(PolyKernNodesL=DRAWN, PolyKernNodesR=DRAWN),
			Layer(PolyKernReferL='o'), Layer()]
	assert store.countExisting(layers) == 3


def test_nothing_drawn_anywhere_counts_nothing():
	assert store.countExisting([Layer(), Layer()]) == 0


# --- Skipping rather than overwriting ---------------------------------------


@pytest.fixture
def measured(monkeypatch):
	"""Let a run reach `writeBubble` without measuring a real outline."""
	monkeypatch.setattr(store.auto, 'auto_settings', lambda font, master, prefs=None: {
			'gap': None, 'step': 5, 'tolerance': 1, 'max_nodes': 40,
			'slope': 0.0, 'max_inset': 20.0, 'amplitude': 1.0})
	monkeypatch.setattr(store.auto, 'resolve_grid', lambda font, master=None, prefs=None: 0)
	monkeypatch.setattr(store.auto, 'auto_bubble_nodes',
			lambda layer, side, **kw: [(7, 0), (7, 700)])
	monkeypatch.setattr(store, 'recordBox', lambda layer, side: None)
	return types.SimpleNamespace(selectedFontMaster=MASTER, masters=[MASTER], upm=1000)


def test_skipping_leaves_the_drawn_wall_alone(measured):
	layer = Layer(PolyKernNodesL=DRAWN)
	store.autoGenerate(measured, True, layers=[layer], skipExisting=True)
	assert layer.userData['PolyKernNodesL'] == DRAWN


def test_skipping_still_draws_the_empty_side(measured):
	layer = Layer(PolyKernNodesL=DRAWN)
	store.autoGenerate(measured, False, layers=[layer], skipExisting=True)
	assert layer.userData['PolyKernNodesR'] == [(7, 0), (7, 700)]


def test_overwriting_replaces_it(measured):
	layer = Layer(PolyKernNodesL=DRAWN)
	store.autoGenerate(measured, True, layers=[layer], skipExisting=False)
	assert layer.userData['PolyKernNodesL'] == [(7, 0), (7, 700)]


def test_a_skipped_side_is_counted_as_skipped(measured):
	done, merged, skipped = store.autoGenerate(
			measured, True, layers=[Layer(PolyKernNodesL=DRAWN)], skipExisting=True)
	assert (done, merged, skipped) == (0, 0, 1)


# --- What the menu does with each answer ------------------------------------


@pytest.fixture
def run(monkeypatch):
	"""Drive `generateBubbles` and record how the store was called."""
	calls = []
	monkeypatch.setattr(store, 'autoGenerate',
			lambda font, isLeft, layers=None, skipExisting=False:
			calls.append(skipExisting) or (0, 0, 0))

	def go(layers, answer):
		asked = []
		font = types.SimpleNamespace(masters=[MASTER], selectedFontMaster=MASTER,
				selectedLayers=layers)
		monkeypatch.setattr(Glyphs, 'font', font, raising=False)
		plugin = kerner.PolyKernKerner.__new__(kerner.PolyKernKerner)
		monkeypatch.setattr(type(plugin), 'askAboutExisting',
				lambda self, count: asked.append(count) or answer, raising=False)
		plugin.generateBubbles(False)
		return asked, calls

	return go


def test_nothing_to_lose_is_never_asked_about(run):
	asked, calls = run([Layer()], kerner.PolyKernKerner.OVERWRITE)
	assert asked == [], 'no question'
	assert calls == [False, False], 'both sides run'


def test_cancel_writes_nothing(run):
	asked, calls = run([Layer(PolyKernNodesL=DRAWN)], kerner.PolyKernKerner.CANCEL)
	assert asked == [1]
	assert calls == [], 'the store was never reached'


def test_overwrite_runs_over_everything(run):
	asked, calls = run([Layer(PolyKernNodesL=DRAWN)], kerner.PolyKernKerner.OVERWRITE)
	assert calls == [False, False]


def test_keep_passes_the_skip_through(run):
	asked, calls = run([Layer(PolyKernNodesL=DRAWN)], kerner.PolyKernKerner.KEEP)
	assert calls == [True, True]


def test_the_question_carries_the_number_of_sides(run):
	# DISTINCT GLYPHS: `generateBubbles` takes each glyph once, however many
	# of its layers are selected.
	layers = [Layer('a', PolyKernNodesL=DRAWN, PolyKernNodesR=DRAWN),
			Layer('b', PolyKernReferR='o')]
	asked, _ = run(layers, kerner.PolyKernKerner.CANCEL)
	assert asked == [3]
