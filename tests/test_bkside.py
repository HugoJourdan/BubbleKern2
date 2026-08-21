# encoding: utf-8
"""The side value, pinned to the exact strings the file format uses.

Every one of these is a literal on purpose. `Side` exists so that forty-two
places stop spelling these keys by hand, which is only an improvement if it
spells them identically - and a key that comes out wrong does not raise, does
not fail anything else, and quietly detaches a wall from the glyph that owns
it. So the mapping is written out here rather than derived.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

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


side_module = _load('BKSide')
LEFT, RIGHT = side_module.LEFT, side_module.RIGHT


# --- The keys ---------------------------------------------------------------


def test_every_key_the_file_format_has():
	assert LEFT.key('Nodes') == 'BubbleKernNodesL'
	assert RIGHT.key('Nodes') == 'BubbleKernNodesR'
	assert LEFT.key('Refer') == 'BubbleKernReferL'
	assert RIGHT.key('Refer') == 'BubbleKernReferR'
	assert LEFT.key('Mirror') == 'BubbleKernMirrorL'
	assert RIGHT.key('Mirror') == 'BubbleKernMirrorR'
	assert LEFT.key('Box') == 'BubbleKernBoxL'
	assert RIGHT.key('Box') == 'BubbleKernBoxR'
	assert LEFT.key('Auto') == 'BubbleKernAutoL'
	assert RIGHT.key('Auto') == 'BubbleKernAutoR'
	assert LEFT.key('Export') == 'BubbleKernExportL'
	assert RIGHT.key('Export') == 'BubbleKernExportR'


def test_a_key_is_a_plain_string():
	# It goes into userData, which is a plist. A str subclass would very
	# probably survive that, and 'very probably' is not a thing to store a
	# font's kerning behind.
	key = LEFT.key('Nodes')
	assert type(key) is str


def test_the_key_is_what_hand_written_concatenation_produced():
	# The forty-two sites this replaces all did one of these three.
	for side in (LEFT, RIGHT):
		for concept in ('Nodes', 'Refer', 'Mirror', 'Box', 'Auto', 'Export'):
			assert side.key(concept) == 'BubbleKern' + concept + side
			assert side.key(concept) == f'BubbleKern{concept}{side}'
			assert side.key(concept) == ('BubbleKern' + concept
					+ ('L' if side.isLeft else 'R'))


# --- Being the letter -------------------------------------------------------


def test_a_side_is_its_own_letter():
	# The point of the str subclass: code that has not been converted yet, and
	# anything outside this plugin, sees exactly what it saw before.
	assert LEFT == 'L'
	assert RIGHT == 'R'
	assert str(LEFT) == 'L'
	assert f'{RIGHT}' == 'R'
	assert 'BubbleKernNodes' + LEFT == 'BubbleKernNodesL'
	assert {'L': 1, 'R': 2}[RIGHT] == 2       # dict lookup, as BKAutoBubble does
	assert sorted((RIGHT, LEFT)) == ['L', 'R']


def test_the_tempdata_names_are_the_ones_the_cache_already_used():
	assert LEFT.tempKey == 'nodesL'
	assert RIGHT.tempKey == 'nodesR'
	assert LEFT.defaultKey == 'defaultL'
	assert RIGHT.defaultKey == 'defaultR'


# --- What follows from which side -------------------------------------------


class _Layer:
	width = 512


def test_the_left_measures_from_the_origin_and_the_right_from_the_advance():
	assert LEFT.origin(_Layer()) == 0
	assert RIGHT.origin(_Layer()) == 512


def test_each_side_knows_the_other():
	assert LEFT.other is RIGHT
	assert RIGHT.other is LEFT


def test_a_boolean_still_names_a_side():
	assert side_module.of(True) is LEFT
	assert side_module.of(False) is RIGHT


def test_the_two_sides_are_the_pair():
	assert side_module.SIDES == (LEFT, RIGHT)
	assert [side.isLeft for side in side_module.SIDES] == [True, False]


def test_the_colours_are_the_ones_the_canvas_draws():
	# Named rather than held, so importing this module needs no AppKit.
	assert LEFT.colorName == 'systemCyanColor'
	assert RIGHT.colorName == 'systemPinkColor'
	from AppKit import NSColor
	assert LEFT.color() == NSColor.systemCyanColor()
	assert RIGHT.color() == NSColor.systemPinkColor()
