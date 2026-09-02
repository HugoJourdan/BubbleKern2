# encoding: utf-8
"""Carrying a font's walls across the rename.

PolyKern reads nothing under the old name, so a file drawn with BubbleKern
opens with its bubbles still in the file and invisible to the plugin. The
script in `Scripts` renames them, and this is what it is allowed to touch:
every key holding the old name, nothing else, and never over a key that the
new plugin has already written.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SCRIPT = (pathlib.Path(__file__).parent.parent / 'Scripts'
		/ 'Rename BubbleKern data to PolyKern.py')


def _load():
	# Imported under a name of its own, so the guard at the foot of the script
	# does not take it for Glyphs running it.
	spec = importlib.util.spec_from_file_location('pk_migrate', SCRIPT)
	module = importlib.util.module_from_spec(spec)
	sys.modules['pk_migrate'] = module
	spec.loader.exec_module(module)
	return module


migrate = _load()

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load_side():
	# The plugin's own key builder, so the script is pinned to what PolyKern
	# actually reads rather than to a string repeated in this file.
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location('pk_side', RESOURCES / 'PKSide.py')
	module = importlib.util.module_from_spec(spec)
	sys.modules['pk_side'] = module
	spec.loader.exec_module(module)
	return module


side = _load_side()


class UserData(dict):
	# Glyphs hands back None for a key nobody set; a plain dict raises.
	def __missing__(self, key):
		return None


class Parameter:
	def __init__(self, name, value):
		self.name, self.value = name, value


class Parameters:
	"""The customParameters proxy: iterates parameters, indexes by name."""

	def __init__(self, pairs=()):
		self._by_name = dict(pairs)

	def __iter__(self):
		return iter([Parameter(k, v) for k, v in self._by_name.items()])

	def __getitem__(self, name):
		return self._by_name.get(name)

	def __setitem__(self, name, value):
		self._by_name[name] = value

	def __delitem__(self, name):
		del self._by_name[name]


class Layer:
	def __init__(self, **userData):
		self.userData = UserData(userData)


class Glyph:
	def __init__(self, name, layers):
		self.name = name
		self.layers = layers
		self.userData = UserData()
		self.undo = 0

	def beginUndo(self):
		self.undo += 1

	def endUndo(self):
		self.undo -= 1


class Master:
	def __init__(self, **parameters):
		self.userData = UserData()
		self.customParameters = Parameters(parameters)


class Font:
	familyName = 'Test'

	def __init__(self, glyphs=(), masters=(), parameters=(), **userData):
		self.glyphs = list(glyphs)
		self.masters = list(masters)
		self.customParameters = Parameters(parameters)
		self.userData = UserData(userData)


@pytest.fixture
def font():
	drawn = Layer(BubbleKernNodesL=[(100, 0)], BubbleKernNodesR=[(-100, 0)],
			BubbleKernBoxL=[0, 0, 600, 700])
	borrowed = Layer(BubbleKernReferL='o', BubbleKernMirrorR=True)
	return Font(
			glyphs=[Glyph('a', [drawn]), Glyph('aacute', [borrowed])],
			masters=[Master(BubbleKernGrid='10')],
			parameters={'BubbleKern': 'depth 20', 'Grid Spacing': '1'},
			BubbleKernPreviewKerning={'A V': -80}, useBubbleKern=True)


# --- What comes across ------------------------------------------------------


def test_the_walls_are_renamed(font):
	migrate.renameFont(font)
	drawn = font.glyphs[0].layers[0].userData
	assert drawn['PolyKernNodesL'] == [(100, 0)]
	assert drawn['PolyKernNodesR'] == [(-100, 0)]
	assert drawn['PolyKernBoxL'] == [0, 0, 600, 700]


def test_the_old_keys_are_gone(font):
	migrate.renameFont(font)
	assert font.glyphs[0].layers[0].userData['BubbleKernNodesL'] is None


def test_a_borrowed_and_a_mirrored_side_come_too(font):
	migrate.renameFont(font)
	borrowed = font.glyphs[1].layers[0].userData
	assert borrowed['PolyKernReferL'] == 'o'
	assert borrowed['PolyKernMirrorR'] is True


def test_the_custom_parameters_come_across(font):
	migrate.renameFont(font)
	assert font.customParameters['PolyKern'] == 'depth 20'
	assert font.masters[0].customParameters['PolyKernGrid'] == '10'


def test_a_key_no_constant_names_comes_across(font):
	# `useBubbleKern` is spelled out in one line of PKKerner and nowhere else.
	migrate.renameFont(font)
	assert font.userData['usePolyKern'] is True
	assert font.userData['PolyKernPreviewKerning'] == {'A V': -80}


def test_nobody_elses_data_is_touched(font):
	migrate.renameFont(font)
	assert font.customParameters['Grid Spacing'] == '1'


def test_the_counts_say_what_happened(font):
	moved, kept, touched = migrate.renameFont(font)
	assert (moved, kept, touched) == (9, 0, 2)


# --- Not clobbering ---------------------------------------------------------


def test_a_key_already_written_by_polykern_wins(font):
	layer = font.glyphs[0].layers[0]
	layer.userData['PolyKernNodesL'] = [(50, 0)]
	moved, kept, _ = migrate.renameFont(font)
	assert layer.userData['PolyKernNodesL'] == [(50, 0)], 'never written over'
	assert layer.userData['BubbleKernNodesL'] == [(100, 0)], 'and left in place'
	assert kept == 1


def test_running_it_twice_changes_nothing_the_second_time(font):
	first = migrate.renameFont(font)
	assert migrate.renameFont(font) == (0, 0, 0)
	assert first[0] == 9


# --- Undo -------------------------------------------------------------------


def test_each_glyph_is_one_undo_step(font):
	migrate.renameFont(font)
	assert [glyph.undo for glyph in font.glyphs] == [0, 0], 'opened and closed'


# --- Going back -------------------------------------------------------------


def test_reverse_puts_it_all_back(font):
	migrate.renameFont(font)
	migrate.renameFont(font, reverse=True)
	assert font.glyphs[0].layers[0].userData['BubbleKernNodesL'] == [(100, 0)]
	assert font.customParameters['BubbleKern'] == 'depth 20'
	assert font.userData['useBubbleKern'] is True


# --- What it says afterwards ------------------------------------------------


def test_the_report_names_the_font_and_the_counts():
	assert migrate.report([('Test', (9, 0, 2))]) == (
			'Test: 9 keys renamed to PolyKern, 2 glyphs.')


def test_the_report_mentions_what_it_left_alone():
	assert 'already had a PolyKern key' in migrate.report([('Test', (8, 1, 2))])


def test_the_report_says_when_there_was_nothing_to_do():
	assert migrate.report([('Test', (0, 0, 0))]) == 'Test: nothing under BubbleKern.'
	assert migrate.report([]) == 'No font is open.'


# --- Pinned to what the plugin reads ----------------------------------------


def test_the_renamed_keys_are_the_ones_polykern_asks_for(font):
	# The point of the whole script. `Side.key` is what every reader in the
	# plugin goes through, so if the two ever drift this is what says so.
	migrate.renameFont(font)
	drawn = font.glyphs[0].layers[0].userData
	assert drawn[side.LEFT.key('Nodes')] == [(100, 0)]
	assert drawn[side.RIGHT.key('Nodes')] == [(-100, 0)]
	assert drawn[side.LEFT.key('Box')] == [0, 0, 600, 700]
	borrowed = font.glyphs[1].layers[0].userData
	assert borrowed[side.LEFT.key('Refer')] == 'o'
	assert borrowed[side.RIGHT.key('Mirror')] is True


def test_every_key_of_the_file_format_survives_a_round_trip(font):
	# One layer carrying all twelve, there and back again.
	layer = font.glyphs[0].layers[0]
	layer.userData.clear()
	for concept in ('Nodes', 'Refer', 'Mirror', 'Box', 'Auto', 'Export'):
		for one in side.SIDES:
			layer.userData['BubbleKern' + concept + str(one)] = f'{concept}{one}'
	migrate.renameFont(font)
	for concept in ('Nodes', 'Refer', 'Mirror', 'Box', 'Auto', 'Export'):
		for one in side.SIDES:
			assert layer.userData[one.key(concept)] == f'{concept}{one}'
	migrate.renameFont(font, reverse=True)
	assert layer.userData['BubbleKernNodesL'] == 'NodesL'
