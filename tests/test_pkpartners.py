# encoding: utf-8
"""Which glyphs the preview stands beside the one being edited.

The ranking is data - André Fuchs's pair list, shipped with the plugin - so
what is pinned here is what the module does WITH it: that the two sides are
answered separately and in the list's own order, that a pair against the word
space is not a pair anybody can look at, that an alternate is asked about as
what it is an alternate of, and that a list typed by hand replaces the lot.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name):
	key = 'pk_' + name
	if key in sys.modules:
		return sys.modules[key]
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location(key, RESOURCES / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	sys.modules[key] = module
	spec.loader.exec_module(module)
	return module


pairs = _load('PKPairs')
# THE MODULE `PKPairs` ITSELF HOLDS, not another copy of it under another name:
# it imports `PKAutoBubble` off sys.path, and a second load would be a second
# module object with the same code and none of the patches.
auto = pairs.auto

# A font that draws six letters and the word space.
TABLE = {'A': 'A', 'V': 'V', 'T': 'T', 'o': 'o', 'n': 'n', 'v': 'v', ' ': 'space'}


class Glyph:
	def __init__(self, name, stored=None):
		self.name = name
		self.userData = {} if stored is None else {pairs.PAIRS_KEY: stored}
		# Glyphs answers None for a key nobody set.
		self.userData = _Missing(self.userData)


class _Missing(dict):
	def __missing__(self, key):
		return None


@pytest.fixture
def listed(monkeypatch):
	"""A short pair list, ranked, standing in for the shipped one."""
	monkeypatch.setattr(auto, 'relevant_pairs',
			lambda: ['A ', 'VA', 'To', ' A', 'AV', 'nA', 'Av', 'oT', 'AT'])
	return TABLE


# --- Which side a partner is on ---------------------------------------------


def test_the_two_sides_are_two_lists(listed):
	before, after = pairs.partners('A', listed)
	assert before == ['V', 'n'], 'the glyphs that come before it'
	assert after == ['V', 'v', 'T'], 'the glyphs that come after it'


def test_the_order_is_the_lists_own(listed):
	"""It is counted from running text, so the first partner is the pair a
	reader meets most often - which is the one worth the top of the row."""
	_before, after = pairs.partners('A', listed)
	assert after == ['V', 'v', 'T'], after


def test_a_pair_against_the_word_space_is_not_one(listed):
	"""`A ` and ` A` are among the commonest pairs in any text, and both of
	them would be a gap in the row with nothing to judge in it."""
	before, after = pairs.partners('A', listed)
	assert 'space' not in before and 'space' not in after


def test_a_partner_the_font_has_no_glyph_for_is_dropped(listed):
	table = dict(listed)
	del table['V']
	before, after = pairs.partners('A', table)
	assert 'V' not in before and 'V' not in after
	assert after == ['v', 'T'], 'and the rest still come'


def test_each_side_is_cut_to_the_limit(listed):
	before, after = pairs.partners('A', listed, limit=1)
	assert (before, after) == (['V'], ['V'])


def test_a_glyph_the_list_never_mentions_gets_nothing(listed):
	assert pairs.partners('o', {'o': 'o'}) == ([], [])


# --- An alternate is asked about as what it is an alternate of ---------------


def test_an_alternate_stands_in_for_its_base(listed):
	"""`A.ss01` has no character of its own, and the pairs `A` turns up in are
	the pairs it is drawn to stand in."""
	before, after = pairs.partners('A.ss01', listed)
	assert after == ['V', 'v', 'T']


def test_a_name_that_opens_with_a_dot_is_its_own_base():
	assert pairs.baseName('.notdef') == '.notdef'
	assert pairs.baseName('Lcommaaccent.ss12') == 'Lcommaaccent'


# --- A list typed by hand ---------------------------------------------------


def test_nothing_stored_is_not_an_empty_list():
	"""None sends the caller to the ranking; an empty list is an answer."""
	assert pairs.chosenPartners(Glyph('A'), TABLE) is None
	assert pairs.chosenPartners(Glyph('A', ''), TABLE) == []


def test_a_stored_list_can_be_glyph_names():
	assert pairs.chosenPartners(Glyph('A', 'V T o'), TABLE) == ['V', 'T', 'o']


def test_a_stored_list_can_be_the_characters_themselves():
	"""`VTo` is not a glyph anybody has, and reading it a character at a time
	is what lets a list be typed without spaces."""
	assert pairs.chosenPartners(Glyph('A', 'VTo'), TABLE) == ['V', 'T', 'o']


def test_a_name_is_read_as_a_name_first():
	table = dict(TABLE, **{'Æ': 'AE'})
	assert pairs.chosenPartners(Glyph('A', 'AE'), table) == ['AE']


def test_a_stored_list_says_it_once():
	assert pairs.chosenPartners(Glyph('A', 'V V T'), TABLE) == ['V', 'T']


# --- The pairs themselves ---------------------------------------------------


def test_the_left_side_comes_first(listed):
	"""The order the info box asks about the two sides in: the pairs where it
	comes second are the ones its LEFT wall has to answer for."""
	shown = pairs.pairsFor(Glyph('A'), 'A', listed, limit=2)
	assert shown == [('V', 'A'), ('n', 'A'), ('A', 'V'), ('A', 'v')]


def test_a_typed_list_replaces_both_sides(listed):
	shown = pairs.pairsFor(Glyph('A', 'T'), 'A', listed)
	assert shown == [('T', 'A'), ('A', 'T')]


def test_a_typed_empty_list_shows_nothing(listed):
	assert pairs.pairsFor(Glyph('A', '  '), 'A', listed) == []


# --- The list that actually ships -------------------------------------------


def test_the_shipped_list_has_something_to_say_about_A():
	"""Not a test of the ranking, which is data. A test that the data is
	there, is read, and is in characters the table can be asked about."""
	before, after = pairs.partners('A', TABLE)
	assert before and after, 'the shipped list said nothing about A'
	assert set(before) <= set(TABLE.values())
	assert set(after) <= set(TABLE.values())


# --- Where the row goes ------------------------------------------------------


PANEL = (0.0, 0.0, 1000.0, 200.0)


def test_the_row_is_scaled_to_whichever_runs_out_first():
	# Width first: a row of twelve pairs, 20000 units, into 920 of room.
	scale, _x, _y = pairs.placeRun(PANEL, 20000, 800, -200)
	assert scale == pytest.approx(920 / 20000)
	# Height first: a short run cannot grow past the panel's own height.
	scale, _x, _y = pairs.placeRun(PANEL, 100, 800, -200)
	assert scale == pytest.approx(200 * 0.7 / 1000)


def test_the_row_is_centred_in_the_panel():
	scale, x, _y = pairs.placeRun(PANEL, 100, 800, -200)
	assert x == pytest.approx((1000 - 100 * scale) / 2.0)


def test_the_baseline_leaves_the_descender_room():
	scale, _x, baseline = pairs.placeRun(PANEL, 100, 800, -200)
	assert baseline == pytest.approx((200 - 1000 * scale) / 2.0 + 200 * scale)


def test_nothing_to_place_is_nowhere_to_put_it():
	assert pairs.placeRun(PANEL, 0, 800, -200) is None
	assert pairs.placeRun((0.0, 0.0, 0.0, 0.0), 100, 800, -200) is None
	assert pairs.placeRun(PANEL, 100, 800, 800) is None
