# encoding: utf-8
"""Which userData keys each writer actually touches.

`Side.key` is spelled correctly - `test_bkside` pins every string - but that
only proves the builder. This proves the WIRING: that writing the left wall
touches the left keys and nothing else, that mirroring one side clears the
other's flag and not its own, and so on.

It matters because the failure mode here is silent. A wall written under the
wrong key does not raise, does not fail a drawing test, and does not show up
until a file that looked fine turns out to have lost a side.

The fakes record every key set or deleted, which is the whole trick.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
from Foundation import NSMakeRect

RESOURCES = (pathlib.Path(__file__).parent.parent / 'BubbleKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name):
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location('bk_' + name, RESOURCES / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	sys.modules['bk_' + name] = module
	spec.loader.exec_module(module)
	return module


store = _load('BKBubbleStore')
logic = _load('BKCommonLogic')
LEFT, RIGHT = store.LEFT, store.RIGHT


class Recorder(dict):
	"""A userData that remembers what was written to it and what was removed."""

	def __init__(self):
		dict.__init__(self)
		self.set, self.deleted = [], []

	def __getitem__(self, key):
		return dict.get(self, key)

	def __setitem__(self, key, value):
		self.set.append(key)
		dict.__setitem__(self, key, value)

	def __delitem__(self, key):
		self.deleted.append(key)
		dict.pop(self, key, None)

	def get(self, key, default=None):
		return dict.get(self, key, default)


class Glyph:
	name = 'a'
	layers = None

	def beginUndo(self):
		pass

	def endUndo(self):
		pass


class Font:
	"""Just enough font for `isReferenceValid` to walk a reference chain."""

	def __init__(self, glyphs):
		self.glyphs = glyphs


class Layer:
	width = 500
	bounds = NSMakeRect(0, 0, 400, 700)
	associatedMasterId = 'm01'

	def __init__(self, name='a', font=None):
		self.userData = Recorder()
		self.tempData = {}
		self.parent = Glyph()
		self.parent.name = name
		self.parent.layers = {self.associatedMasterId: self}
		self.paths, self.components, self.shapes = [1], [], [1]
		self._font = font

	def font(self):
		return self._font


def _pair():
	"""A layer and the glyph it can legitimately refer to."""
	glyphs = {}
	font = Font(glyphs)
	layer = Layer('a', font)
	target = Layer('o', font)
	glyphs['a'], glyphs['o'] = layer.parent, target.parent
	return layer, target


@pytest.fixture(params=[True, False], ids=['left', 'right'])
def side(request):
	return store.of(request.param)


# --- Writing a wall ---------------------------------------------------------


def test_writing_a_wall_touches_that_side_and_no_other(side):
	layer = Layer()
	store.writeBubble(layer, side, nodes=[(0, 0), (0, 700)])
	assert set(layer.userData.set) == {side.key('Nodes'), side.key('Box')}
	assert not [key for key in layer.userData.set
			if key.endswith(side.other)], 'wrote to the other side'


def test_writing_a_wall_records_the_box_it_was_drawn_against(side):
	layer = Layer()
	store.writeBubble(layer, side, nodes=[(0, 0), (0, 700)])
	# The advance goes in with it: telling an LSB change from an RSB one needs
	# both, and an LSB change moves the ink AND the advance.
	assert layer.userData[side.key('Box')] == [0, 0, 400, 700, 500]


def test_a_reference_and_a_drawing_are_alternatives(side):
	layer, _target = _pair()
	layer.userData[side.key('Nodes')] = [(0, 0), (0, 700)]
	layer.userData.set.clear()
	assert store.writeBubble(layer, side, refer='o') is True
	assert layer.userData[side.key('Refer')] == 'o'
	assert side.key('Nodes') in layer.userData.deleted, 'left dead nodes behind'


# --- Mirroring --------------------------------------------------------------


def test_mirroring_sets_its_own_flag_and_clears_the_others(side):
	layer = Layer()
	layer.userData[side.other.key('Mirror')] = True
	layer.userData[side.key('Refer')] = 'o'
	layer.userData[side.key('Nodes')] = [(0, 0), (0, 700)]
	layer.userData.set.clear()

	done, written, other = store.syncBubble(None, side.isLeft, layers=[layer])

	assert (done, written, other) == (1, side, side.other)
	assert layer.userData.set == [side.key('Mirror')]
	assert set(layer.userData.deleted) == {
		side.other.key('Mirror'),   # both sides mirroring means neither does
		side.key('Refer'),          # the three ways a side gets its shape
		side.key('Nodes'),          # are exclusive
	}


# --- Following the spacing --------------------------------------------------


def test_a_spacing_move_rewrites_only_its_own_side(side):
	layer = Layer()
	store.recordBox(layer, side)
	layer.userData[side.key('Nodes')] = [(-40, 0), (-40, 700)]
	layer.width = 560          # the advance moved; the ink did not
	layer.userData.set.clear()

	assert logic.shiftBubbleForSpacing(layer, side) is (not side.isLeft)
	assert not [key for key in layer.userData.set
			if key.endswith(side.other)], 'touched the other side'


# --- The whole surface ------------------------------------------------------


def test_no_writer_invents_a_key_outside_the_known_six():
	"""Whatever gets written, it is one of the six concepts the format has."""
	concepts = ('Nodes', 'Refer', 'Mirror', 'Box', 'Auto', 'Export')
	allowed = {f'BubbleKern{concept}{letter}'
			for concept in concepts for letter in 'LR'}
	touched = set()
	for one in (LEFT, RIGHT):
		layer = Layer()
		store.writeBubble(layer, one, nodes=[(0, 0), (0, 700)])
		store.syncBubble(None, one.isLeft, layers=[layer])
		store.recordBox(layer, one)
		touched |= set(layer.userData.set) | set(layer.userData.deleted)
	assert touched, 'the fakes recorded nothing, so this proves nothing'
	assert touched <= allowed, f'unknown keys: {sorted(touched - allowed)}'
