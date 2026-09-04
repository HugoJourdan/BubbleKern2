# encoding: utf-8
"""The row of pairs, as far as it can be pinned without a preview panel.

The drawing itself needs Glyphs. What does not, and is where the mistakes
would be, is the arithmetic around it: which call of a pass draws the row, when
the panel counts as open, and what the row's advances add up to - the total
being what centres it, so a gap counted at the wrong end moves the whole row.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

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


preview = _load('PKPairsPreview')
pairs = preview.pairs


class Layer:
	def __init__(self, name, width):
		self.width = width
		self.associatedMasterId = 'm1'
		self.parent = types.SimpleNamespace(name=name, userData={})


class Font:
	upm = 1000

	def __init__(self, *layers):
		self._layers = {layer.parent.name: layer for layer in layers}
		self.glyphs = self

	def __getitem__(self, name):
		layer = self._layers.get(name)
		if layer is None:
			return None
		return types.SimpleNamespace(name=name, layers={'m1': layer},
				userData={})


@pytest.fixture
def reporter():
	# NO __init__: it registers with the badge and reaches for the app. Every
	# method under test is a plain python_method that never does.
	return preview.PolyKernPairs.__new__(preview.PolyKernPairs)


# --- Which call of a pass draws the row -------------------------------------


def test_the_first_call_of_a_pass_draws_it():
	assert preview.opensPass(120.0, None) is True


def test_a_later_call_of_the_same_pass_does_not():
	"""Glyphs hands each glyph its own coordinates, so the panel's left edge
	sits further behind the origin as the pass goes on."""
	assert preview.opensPass(-380.0, 120.0, layerCount=4) is False


def test_a_new_pass_starts_where_the_last_one_did():
	assert preview.opensPass(120.0, -380.0, layerCount=4) is True


def test_a_text_of_one_glyph_is_one_call_and_always_opens():
	"""The case the clip cannot answer: with nothing else in the text the only
	thing moving the panel's edge between frames is the drag itself, and
	dragging one way looks exactly like a later call in the same pass."""
	assert preview.opensPass(-380.0, 120.0, layerCount=1) is True


# --- When the panel counts as open ------------------------------------------


def test_a_shut_panel_is_not_open():
	assert preview.previewIsOpen(types.SimpleNamespace(previewHeight=0)) is False
	assert preview.previewIsOpen(None) is False


def test_a_panel_dragged_almost_shut_is_not_open_either():
	tab = types.SimpleNamespace(previewHeight=preview.PREVIEW_MIN_HEIGHT - 1)
	assert preview.previewIsOpen(tab) is False


def test_an_open_panel_is():
	tab = types.SimpleNamespace(previewHeight=200.0)
	assert preview.previewIsOpen(tab) is True


# --- What the row adds up to -------------------------------------------------


def _row(reporter, monkeypatch, shown, widths, kern=0.0):
	layers = [Layer(name, width) for name, width in widths.items()]
	font = Font(*layers)
	edited = layers[0]
	monkeypatch.setattr(reporter, 'currentLayer', lambda: (font, edited),
			raising=False)
	monkeypatch.setattr(reporter, 'namesTable', lambda f: {}, raising=False)
	monkeypatch.setattr(reporter, 'kernBetween', lambda f, l, r: kern,
			raising=False)
	monkeypatch.setattr(pairs, 'pairsFor', lambda *a, **k: shown)
	return reporter.rowCells()


def test_the_row_is_the_pairs_end_to_end(reporter, monkeypatch):
	cells, total = _row(reporter, monkeypatch, [('A', 'V'), ('V', 'A')],
			{'A': 700, 'V': 600})
	assert [layer.parent.name for layer, _advance in cells] == ['A', 'V', 'V', 'A']
	gap = 1000 * pairs.PAIR_GAP_EM
	# Two pairs of 1300, one gap between them - and not one after the last.
	assert total == pytest.approx(1300 + gap + 1300)


def test_the_kern_is_in_the_advance(reporter, monkeypatch):
	"""What the row is FOR: the pair moves when the wall does."""
	cells, total = _row(reporter, monkeypatch, [('A', 'V')],
			{'A': 700, 'V': 600}, kern=-120.0)
	assert cells[0][1] == pytest.approx(700 - 120), 'the kern rides on the first'
	assert total == pytest.approx(700 - 120 + 600)


def test_a_pair_the_font_cannot_spell_is_left_out(reporter, monkeypatch):
	cells, total = _row(reporter, monkeypatch, [('A', 'missing'), ('A', 'V')],
			{'A': 700, 'V': 600})
	assert [layer.parent.name for layer, _advance in cells] == ['A', 'V']
	assert total == pytest.approx(1300)


def test_nothing_to_show_is_nothing_to_place(reporter, monkeypatch):
	assert _row(reporter, monkeypatch, [], {'A': 700}) == ([], 0.0)


# --- The switch --------------------------------------------------------------


class _Defaults(dict):
	def __missing__(self, key):
		return None


def _withDefaults(reporter, monkeypatch, visible=()):
	defaults = _Defaults({preview.VISIBLE_REPORTERS: list(visible)})
	monkeypatch.setattr(preview.Glyphs, 'defaults', defaults, raising=False)
	monkeypatch.setattr(preview.previewbadge, 'refresh', lambda *a, **k: None)
	monkeypatch.setattr(reporter, 'className', lambda: 'PolyKernPairs',
			raising=False)
	return defaults


def test_ticked_in_the_view_menu_is_the_whole_of_being_on(reporter, monkeypatch):
	_withDefaults(reporter, monkeypatch, visible=['PolyKernPairs'])
	assert reporter.showing() is True


def test_not_in_the_list_is_off(reporter, monkeypatch):
	_withDefaults(reporter, monkeypatch, visible=['SomebodyElse'])
	assert reporter.showing() is False


def test_the_badge_flips_the_same_switch_the_menu_does(reporter, monkeypatch):
	defaults = _withDefaults(reporter, monkeypatch, visible=['SomebodyElse'])
	reporter.setShowing(True)
	assert defaults[preview.VISIBLE_REPORTERS] == ['SomebodyElse', 'PolyKernPairs']
	reporter.setShowing(False)
	assert defaults[preview.VISIBLE_REPORTERS] == ['SomebodyElse']


def test_switching_it_where_it_already_is_writes_nothing(reporter, monkeypatch):
	defaults = _withDefaults(reporter, monkeypatch, visible=['PolyKernPairs'])
	written = []
	monkeypatch.setattr(preview.Glyphs, 'redraw', lambda: written.append(1),
			raising=False)
	reporter.setShowing(True)
	assert not written


# --- Choosing them by hand ---------------------------------------------------


def test_the_menu_names_the_glyph_it_would_edit(reporter, monkeypatch):
	_withDefaults(reporter, monkeypatch, visible=['PolyKernPairs'])
	layer = Layer('A', 700)
	monkeypatch.setattr(reporter, 'currentLayer', lambda: (None, layer),
			raising=False)
	items = reporter.conditionalContextMenus()
	assert len(items) == 1
	assert 'A' in items[0]['name'], items[0]['name']
	assert items[0]['action'] == 'editPairs:'


def test_the_menu_says_nothing_while_the_row_is_off(reporter, monkeypatch):
	"""That menu is shared by everything, and a control for something you
	cannot see is only in the way."""
	_withDefaults(reporter, monkeypatch, visible=[])
	assert reporter.conditionalContextMenus() == []
