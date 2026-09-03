# encoding: utf-8
"""How many pairs a run will set, and what the relevant list does to that.

The list ADDS to what the preset asks for; it does not narrow it. That makes
the count arithmetic load-bearing: the total used to be a sum of the row
products with the box clear and a deduped set with it ticked, so a box that
can only ever add pairs could make the number go DOWN.
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


_load('PKBubbleStore', 'PKBubbleStore')
sys.modules.setdefault('PKTool', types.SimpleNamespace(mainDrawingHandler=None))
kerner = _load('PKKerner')


def row(left, right, flipped=False, kern=True):
	return {'Kern': kern, 'Left': left, 'Right': right, 'Add Flipped': flipped,
			'Pairs': str(len(left.split()) * len(right.split()) * (2 if flipped else 1))}


@pytest.fixture
def plugin(monkeypatch):
	"""A kerner whose relevant list is a known two pairs."""
	def make(relevant=(('T', 'o'), ('V', 'a')), included=False):
		p = kerner.PolyKernKerner.__new__(kerner.PolyKernKerner)
		p.font = types.SimpleNamespace(glyphs=[])
		monkeypatch.setattr(kerner.PKCommonLogic, 'namesByCharacter',
				lambda font: {}, raising=False)
		monkeypatch.setattr(kerner.PKAutoBubble, 'relevant_pair_names',
				lambda names, limit=None: set(relevant), raising=False)
		monkeypatch.setattr(kerner.PKAutoBubble, '_pref',
				lambda key, default=None, prefs=None: included
				if key == kerner.PKAutoBubble.PREF_INCLUDE_RELEVANT else default,
				raising=False)
		return p
	return make


# --- the preset's own pairs -------------------------------------------------


def test_a_row_is_its_cartesian_product(plugin):
	assert len(plugin().presetPairs([row('A B', 'x y z')])) == 6


def test_flipped_adds_the_other_direction(plugin):
	pairs = plugin().presetPairs([row('A', 'x', flipped=True)])
	assert pairs == {('A', 'x'), ('x', 'A')}


def test_a_pair_two_rows_both_name_is_one_pair(plugin):
	"""The Pairs column would say 2. A run sets it once."""
	pairs = plugin().presetPairs([row('A', 'x'), row('A', 'x')])
	assert len(pairs) == 1


def test_the_total_dedupes_across_rows(plugin):
	rows = [row('A', 'x'), row('A', 'x')]
	assert sum(int(r['Pairs']) for r in rows) == 2, 'the column still says two'
	assert plugin().totalCount(rows) == 1, 'the total should not'


# --- what the relevant list does --------------------------------------------


def test_the_list_is_left_out_when_not_asked(plugin):
	assert plugin(included=False).totalCount([row('A', 'x')]) == 1


def test_the_list_adds_to_the_preset(plugin):
	"""Two pairs of its own plus the row's one, none of them shared."""
	assert plugin(included=True).totalCount([row('A', 'x')]) == 3


def test_it_does_not_narrow_the_preset(plugin):
	"""The old behaviour kept only pairs on the list - this row would be 0."""
	assert plugin(included=True).totalCount([row('Q', 'j')]) >= 1


def test_a_pair_already_asked_for_is_not_counted_twice(plugin):
	assert plugin(included=True).totalCount([row('T', 'o')]) == 2


def test_including_can_never_lower_the_total(plugin):
	rows = [row('A B C', 'x y z', flipped=True), row('T', 'o')]
	assert (plugin(included=True).totalCount(rows)
			>= plugin(included=False).totalCount(rows))


# --- where the run applies it ------------------------------------------------


def test_the_list_is_added_before_the_selection_narrows_it():
	"""Otherwise "Kern Pairs for Selected Glyphs" quietly reaches the whole
	font: the added pairs have to face the same question the preset's do.
	Read off the source because `kernOpenType` wants a live font to run."""
	source = (RESOURCES / 'PKCommonLogic.py').read_text()
	added = source.index('pairsList |= PKAutoBubble.relevant_pair_names')
	narrowed = source.index('if selectedLayersOnly:')
	assert added < narrowed, 'the relevant pairs escape the selection'


# --- the Kern column ---------------------------------------------------------

import PKCommonLogic  # noqa: E402  (the resources are on sys.path by now)


def test_a_row_switched_off_contributes_nothing(plugin):
	assert plugin().presetPairs([row('A B', 'x y', kern=False)]) == set()


def test_the_other_rows_still_count(plugin):
	rows = [row('A B', 'x y', kern=False), row('T', 'o')]
	assert plugin().presetPairs(rows) == {('T', 'o')}


def test_the_total_leaves_switched_off_rows_out(plugin):
	rows = [row('A B C', 'x y z', kern=False), row('T', 'o')]
	assert plugin().totalCount(rows) == 1


def test_a_row_with_no_flag_at_all_is_on(plugin):
	"""Rows made before the column existed, still in memory."""
	bare = {'Left': 'A', 'Right': 'x', 'Add Flipped': False, 'Pairs': '1'}
	assert plugin().presetPairs([bare]) == {('A', 'x')}


def test_switching_a_row_off_can_only_lower_the_total(plugin):
	on = [row('A B C', 'x y z', flipped=True)]
	off = [row('A B C', 'x y z', flipped=True, kern=False)]
	assert plugin().totalCount(off) < plugin().totalCount(on)


# --- what a saved preset means -----------------------------------------------


def test_a_three_long_preset_row_is_on():
	"""Every preset saved before the Kern column existed."""
	assert PKCommonLogic.rowIsOn(('A B', 'x y', True)) is True


def test_a_four_long_row_says_for_itself():
	assert PKCommonLogic.rowIsOn(('A B', 'x y', True, False)) is False
	assert PKCommonLogic.rowIsOn(('A B', 'x y', True, True)) is True


def test_the_run_skips_switched_off_rows():
	"""Read off the source: `kernOpenType` wants a live font to run."""
	source = (RESOURCES / 'PKCommonLogic.py').read_text()
	loop = source.index('for perm in preset:')
	assert 'if not rowIsOn(perm):' in source[loop:loop + 200]
