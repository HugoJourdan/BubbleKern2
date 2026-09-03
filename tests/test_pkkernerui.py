# encoding: utf-8
"""The kerner window, actually built.

Layout is the one part of this plugin that cannot be reasoned about: a typo in
a visual-format string or an anchor pinned to the wrong view raises nothing
until somebody opens the window, and by then it is in Glyphs. So build it here
and measure it. Needs a GUI session - AppKit will not lay out over a plain ssh.
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

from AppKit import NSApplication  # noqa: E402
from GlyphsApp import Glyphs  # noqa: E402  (the conftest stub)


@pytest.fixture
def window(monkeypatch):
	"""The Generate Kerning tab, built and laid out. -> (plugin, group0)"""
	NSApplication.sharedApplication()
	font = types.SimpleNamespace(filepath='/tmp/Test.glyphs', familyName='Test',
			glyphs=[], masters=[], selectedFontMaster=None, selectedLayers=[],
			upm=1000)
	monkeypatch.setattr(Glyphs, 'font', font, raising=False)
	preset = {'Default': [('A B', 'x y', True)]}
	monkeypatch.setitem(Glyphs.defaults, 'com.Tosche.PolyKern.presetsDic', preset)

	plugin = kerner.PolyKernKerner.__new__(kerner.PolyKernKerner)
	plugin.loadedPresetName = 'Default'
	plugin.presetsDic = dict(preset)
	plugin.buildWindow()
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	yield plugin, plugin.w.tabs[0].group0
	plugin.w.close()


def test_the_window_builds_and_lays_out(window):
	"""If a rule is malformed this is where it goes bang."""
	plugin, group = window
	assert plugin.w.getNSWindow() is not None


def test_the_kern_column_comes_first(window):
	_, group = window
	names = [str(c.identifier()) for c in group.permList.getNSTableView().tableColumns()]
	assert names == ['Kern', 'Left', 'Right', 'Add Flipped', 'Pairs']


def test_the_add_and_delete_buttons_sit_on_the_list(window):
	"""Overlapping its bottom right corner, not in a row underneath it."""
	_, group = window
	listView = group.permList.getNSScrollView()
	bounds = listView.bounds()
	for name in ('addButton', 'delButton'):
		button = getattr(group, name).getNSButton()
		frame = listView.convertRect_fromView_(button.frame(), button.superview())
		assert frame.origin.x >= bounds.origin.x, f'{name} off the left'
		assert (frame.origin.x + frame.size.width
				<= bounds.origin.x + bounds.size.width), f'{name} past the right'
		assert frame.origin.y >= bounds.origin.y, f'{name} above the list'
		assert (frame.origin.y + frame.size.height
				<= bounds.origin.y + bounds.size.height), f'{name} below the list'


def test_they_sit_in_the_bottom_right_of_it(window):
	"""The list is flipped, so further down is a larger y."""
	_, group = window
	listView = group.permList.getNSScrollView()
	assert listView.isFlipped(), 'the corner test below assumes a flipped list'
	bounds = listView.bounds()
	button = group.delButton.getNSButton()
	frame = listView.convertRect_fromView_(button.frame(), button.superview())
	assert frame.origin.x > bounds.size.width * 0.75, 'not in the right quarter'
	assert frame.origin.y > bounds.size.height * 0.75, 'not in the bottom quarter'


def test_they_are_smaller_than_the_row_they_used_to_sit_in(window):
	_, group = window
	button = group.addButton.getNSButton()
	assert button.frame().size.width == pytest.approx(kerner.PolyKernKerner.LIST_BUTTON_W)
	assert button.frame().size.height == pytest.approx(kerner.PolyKernKerner.LIST_BUTTON_H)
	assert button.frame().size.width < 40, 'no smaller than the old 40x24'
	assert button.frame().size.height < 24


def test_one_button_starts_a_run(window):
	"""Kern All Pairs and Kern Pairs for Selected Glyphs are one Apply Kerning."""
	_, group = window
	buttons = window[0].w.tabs[0].group1
	assert hasattr(buttons, 'applyButton')
	assert not hasattr(buttons, 'allButton') and not hasattr(buttons, 'selButton')
	assert buttons.applyButton.getTitle() == 'Apply Kerning'


def test_there_is_no_write_groups_switch_any_more(window):
	"""It is not optional now - PKCommonLogic sets useGroups True outright."""
	_, group = window
	assert not hasattr(window[0].w.tabs[0].group1, 'writeGroups')
	source = (RESOURCES / 'PKCommonLogic.py').read_text()
	assert 'useGroups = True' in source


def test_the_total_counts_only_the_ticked_rows(window):
	plugin, group = window
	group.permList.set([
		{'Kern': True, 'Left': 'A B', 'Right': 'x y', 'Add Flipped': False, 'Pairs': '4'},
		{'Kern': False, 'Left': 'T V W', 'Right': 'a e o', 'Add Flipped': False, 'Pairs': '9'},
	])
	plugin.refreshTotal()
	assert group.total.get().endswith('4'), group.total.get()
