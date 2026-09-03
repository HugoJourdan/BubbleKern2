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
# UNDER ITS PLAIN NAME TOO. The tool does `import PKKerner` to find the
# window the settings live in, and executing the file twice re-registers
# its ObjC classes.
sys.modules.setdefault('PKKerner', kerner)

from AppKit import NSApplication  # noqa: E402
from Foundation import NSObject  # noqa: E402
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
	yield plugin, plugin.w.kernerPane.tabs[0].group0
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
	buttons = window[0].w.kernerPane.tabs[0].group1
	assert hasattr(buttons, 'applyButton')
	assert not hasattr(buttons, 'allButton') and not hasattr(buttons, 'selButton')
	assert buttons.applyButton.getTitle() == 'Apply Kerning'


def test_there_is_no_write_groups_switch_any_more(window):
	"""It is not optional now - PKCommonLogic sets useGroups True outright."""
	_, group = window
	assert not hasattr(window[0].w.kernerPane.tabs[0].group1, 'writeGroups')
	source = (RESOURCES / 'PKCommonLogic.py').read_text()
	assert 'useGroups = True' in source


def test_the_total_counts_only_the_ticked_rows(window):
	plugin, group = window
	group.permList.set([
		{'Kern': True, 'Left': 'A B', 'Right': 'x y', 'Add Flipped': False, 'Pairs': '4'},
		{'Kern': False, 'Left': 'T V W', 'Right': 'a e o', 'Add Flipped': False, 'Pairs': '9'},
	])
	plugin.refreshTotal()
	total = plugin.w.kernerPane.tabs[0].group1.total
	assert total.get().endswith('4'), total.get()


# --- where the total sits, and what it says ---------------------------------


def test_the_total_says_what_it_counts(window):
	plugin, _ = window
	assert plugin.w.kernerPane.tabs[0].group1.total.get().startswith('Total Pairs to Kern')


def _visible(view):
	"""What the eye sees of a control. -> NSRect

	NOT ITS FRAME. A bezelled NSButton's frame is five points wider and six
	taller than the box that gets drawn, and auto layout lines views up by the
	drawn box - so comparing frames says two aligned views are five apart.
	"""
	return view.alignmentRectForFrame_(view.frame())


def test_the_total_sits_over_the_apply_button(window):
	"""It used to be under the list, a column away from the button that acts
	on it. Both are in the bottom bar now, right-aligned together."""
	plugin, _ = window
	bar = plugin.w.kernerPane.tabs[0].group1
	total = _visible(bar.total.getNSTextField())
	button = _visible(bar.applyButton.getNSButton())
	# the bar is not flipped, so higher on screen is a larger y
	assert total.origin.y >= button.origin.y + button.size.height, 'not above it'
	assert (abs((total.origin.x + total.size.width)
			- (button.origin.x + button.size.width)) < 2), 'not aligned right'


def test_the_total_and_the_button_are_not_touching(window):
	plugin, _ = window
	bar = plugin.w.kernerPane.tabs[0].group1
	total = _visible(bar.total.getNSTextField())
	button = _visible(bar.applyButton.getNSButton())
	gap = total.origin.y - (button.origin.y + button.size.height)
	assert 2 <= gap <= 10, f'gap of {gap}'


def test_the_list_is_no_longer_squeezed_by_the_total(window):
	"""group0 is the list and the preview now; nothing else."""
	_, group = window
	assert not hasattr(group, 'total')


# --- the info button and its popover ----------------------------------------


def test_there_is_an_info_button_beside_the_checkbox(window):
	plugin, _ = window
	bar = plugin.w.kernerPane.tabs[0].group1
	assert hasattr(bar, 'infoButton')
	check = bar.includeRelevant.getNSButton().frame()
	info = bar.infoButton.getNSButton().frame()
	assert info.origin.x >= check.origin.x + check.size.width - 2, 'not beside it'


def test_the_popover_lists_every_relevant_pair(window):
	plugin, _ = window
	rows = plugin.relevantRows()
	assert len(rows) == len(kerner.PKAutoBubble.relevant_pairs())
	assert rows[0]['#'] == 1


def test_a_space_is_spelled_out_rather_than_left_blank(window):
	"""126 of the pairs start with one, and an empty cell reads as a bug."""
	plugin, _ = window
	spaced = [r for r in plugin.relevantRows() if r['Pair'][0] == ' ']
	assert spaced, 'the list has no space-led pairs to check'
	assert spaced[0]['Left'] == 'space'


def test_the_blurb_says_the_list_adds_rather_than_narrows(window):
	plugin, _ = window
	blurb = plugin.RELEVANT_BLURB.format(count=1234)
	assert 'ADDS' in blurb and 'does not narrow' in blurb
	assert '1,234' in blurb, 'the count is not filled in'


def test_the_popover_opens_and_carries_the_pairs(window):
	"""Built for real - a bad posSize or column raises here, not in Glyphs."""
	plugin, _ = window
	plugin.showRelevantPairs(plugin.w.kernerPane.tabs[0].group1.infoButton)
	popover = getattr(plugin, 'relevantPopover', None)
	assert popover is not None, 'the popover was not built'
	assert len(popover.pairs.get()) == len(kerner.PKAutoBubble.relevant_pairs())
	popover.close()


# --- the corner buttons -----------------------------------------------------


def test_the_corner_buttons_keep_clear_of_the_corner(window):
	"""Six points further in than they were."""
	_, group = window
	listView = group.permList.getNSScrollView()
	bounds = listView.bounds()
	frame = listView.convertRect_fromView_(
		group.delButton.getNSButton().frame(), group.delButton.getNSButton().superview())
	right = bounds.origin.x + bounds.size.width - (frame.origin.x + frame.size.width)
	below = bounds.origin.y + bounds.size.height - (frame.origin.y + frame.size.height)
	assert right == pytest.approx(kerner.PolyKernKerner.LIST_BUTTON_INSET)
	assert below == pytest.approx(kerner.PolyKernKerner.LIST_BUTTON_INSET)
	assert kerner.PolyKernKerner.LIST_BUTTON_INSET >= 12


def test_the_blurb_gets_the_room_its_words_need(window):
	"""It was given a round 106 points, wanted 126, and lost two lines."""
	plugin, _ = window
	plugin.showRelevantPairs(plugin.w.kernerPane.tabs[0].group1.infoButton)
	popover = plugin.relevantPopover
	text = plugin.RELEVANT_BLURB.format(count=len(plugin.relevantRows()))
	wide = plugin.POPOVER_SIZE[0] - plugin.POPOVER_MARGIN * 2
	needed = plugin.paragraphHeight(text, wide)
	box = popover.blurb.getNSTextField().frame()
	assert box.size.height >= needed, f"{box.size.height} for {needed}"
	popover.close()


def test_a_longer_paragraph_would_get_a_taller_box(window):
	"""The height is measured, so it follows the words rather than a number
	somebody typed once."""
	plugin, _ = window
	wide = plugin.POPOVER_SIZE[0] - plugin.POPOVER_MARGIN * 2
	short = plugin.paragraphHeight("One line.", wide)
	long = plugin.paragraphHeight("One line. " * 200, wide)
	assert long > short * 4, f"{short} then {long}"


def test_the_pairs_still_fit_under_it(window):
	plugin, _ = window
	plugin.showRelevantPairs(plugin.w.kernerPane.tabs[0].group1.infoButton)
	popover = plugin.relevantPopover
	content = popover.getNSPopover().contentViewController().view().frame()
	list_frame = popover.pairs.getNSScrollView().frame()
	blurb = popover.blurb.getNSTextField().frame()
	assert list_frame.size.height > 100, "no room left for the pairs"
	assert (list_frame.origin.y + list_frame.size.height
			<= content.size.height + 1), "the list runs off the popover"
	# the two do not overlap: the list starts below the paragraph
	assert blurb.size.height + 14 <= content.size.height - list_frame.size.height
	popover.close()


# --- one window, two panes -------------------------------------------------


def test_the_window_is_one_polykern_not_a_kerner(window):
	plugin, _ = window
	assert plugin.w.getNSWindow().title() == 'PolyKern'


def test_both_panes_exist(window):
	plugin, _ = window
	assert hasattr(plugin.w, 'kernerPane') and hasattr(plugin.w, 'settingsPane')


def test_the_toolbar_offers_the_two_panes(window):
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert toolbar is not None, 'no toolbar'
	names = [str(i.itemIdentifier()) for i in toolbar.items()]
	assert names == [plugin.KERNER, plugin.SETTINGS], names


def test_showing_one_pane_hides_the_other(window):
	plugin, _ = window
	plugin.showPane(plugin.SETTINGS)
	assert plugin.w.kernerPane.getNSView().isHidden()
	assert not plugin.w.settingsPane.getNSView().isHidden()
	plugin.showPane(plugin.KERNER)
	assert not plugin.w.kernerPane.getNSView().isHidden()
	assert plugin.w.settingsPane.getNSView().isHidden()


def test_the_toolbar_follows_the_pane(window):
	plugin, _ = window
	plugin.showPane(plugin.SETTINGS)
	toolbar = plugin.w.getNSWindow().toolbar()
	assert str(toolbar.selectedItemIdentifier()) == plugin.SETTINGS


def test_it_opens_on_the_kerner(window):
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert str(toolbar.selectedItemIdentifier()) == plugin.KERNER


def test_with_no_tool_the_settings_pane_says_so(window):
	"""The tool is a separate principal class and may not exist yet. The
	fixture leaves it unloaded, so this is the pane the tests build."""
	plugin, _ = window
	assert hasattr(plugin.w.settingsPane, 'notLoaded')
	assert plugin.settingsTool is None


# --- with the tool actually there ------------------------------------------


@pytest.fixture
def withTool(monkeypatch):
	"""The same window, but with a real tool for the settings pane."""
	tool_module = _load('PKTool')
	tool = tool_module.PolyKernTool.__new__(tool_module.PolyKernTool)
	monkeypatch.setattr(sys.modules['PKTool'], 'mainDrawingHandler', tool,
			raising=False)
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
	yield plugin, tool
	plugin.w.close()


def test_the_settings_are_built_into_the_pane(withTool):
	plugin, tool = withTool
	assert plugin.settingsTool is tool, 'the pane was not filled'
	assert not hasattr(plugin.w.settingsPane, 'notLoaded')


def test_the_tool_reaches_its_controls_through_the_pane(withTool):
	"""Every settings method says `self.setW`. It is the pane now."""
	plugin, tool = withTool
	assert tool.setW is plugin.w.settingsPane


def test_the_settings_controls_are_all_there(withTool):
	"""The three sections the floating window used to build, unchanged."""
	plugin, _ = withTool
	pane = plugin.w.settingsPane
	for named in ('previewText', 'shapeTitle', 'line0'):
		assert hasattr(pane, named), f'{named} missing from the settings pane'


def test_closing_the_window_saves_what_the_sliders_say(withTool):
	"""It only hides, so the tool's own close handler never runs."""
	plugin, tool = withTool
	applied = []
	type(tool).applySettings = lambda self: applied.append(True)
	plugin.windowShouldClose_(None)
	assert applied == [True], 'the settings were not saved on close'


def test_the_tool_menu_opens_the_same_settings(withTool, monkeypatch):
	"""The tool has its own Settings entry. If it opened the old standalone
	window it would point setW at that one, leaving the pane in this window
	looking right and driving nothing."""
	plugin, tool = withTool
	monkeypatch.setattr(kerner, 'mainKerner', plugin, raising=False)
	standalone = []
	type(tool).openSettingsWindow = lambda self: standalone.append(True)
	tool.showSettings()
	assert standalone == [], 'it opened the old window as well'
	assert tool.setW is plugin.w.settingsPane


def test_without_the_kerner_the_tool_still_has_its_own_window(withTool, monkeypatch):
	"""The fallback. No pane exists to strand in that case."""
	plugin, tool = withTool
	monkeypatch.setattr(kerner, 'mainKerner', None, raising=False)
	standalone = []
	type(tool).openSettingsWindow = lambda self: standalone.append(True)
	tool.showSettings()
	assert standalone == [True]


def test_start_publishes_the_plugin_for_the_tool_to_find():
	source = (RESOURCES / 'PKKerner.py').read_text()
	assert 'global mainKerner' in source and 'mainKerner = self' in source


# --- the Edit menu ---------------------------------------------------------


class _MenuTarget(NSObject):
	"""Something with real selectors to hang the menu items on.

	NSMenuItem wants a SEL, and the plugin's base class is faked here by a
	plain Python class - so its methods are plain methods and pyobjc will not
	take them. In Glyphs the base is an ObjC class and they are selectors.
	`buildMenu` is a python_method, so it can be called against this instead.
	"""
	MENU_TITLE = None  # filled in by the fixture

	def showWindow_(self, sender): pass
	def generateSelected_(self, sender): pass
	def generateAllMasters_(self, sender): pass
	def clearSelected_(self, sender): pass
	def clearAllMasters_(self, sender): pass


@pytest.fixture
def menu():
	"""The submenu, built for real. -> (title, parent, items)"""
	target = _MenuTarget.alloc().init()
	target.MENU_TITLE = kerner.PolyKernKerner.MENU_TITLE
	parent = kerner.PolyKernKerner.buildMenu(target)
	return kerner.PolyKernKerner, parent, list(parent.submenu().itemArray())


def test_the_submenu_hangs_off_a_polykern_item(menu):
	_, parent, _ = menu
	assert str(parent.title()) == 'PolyKern'


def test_one_entry_opens_the_window(menu):
	"""There is one window now, so there is one entry for it."""
	plugin, _, items = menu
	assert str(items[0].title()) == plugin.MENU_TITLE
	assert str(items[0].title()) == 'PolyKern UI'


def test_there_is_no_separate_settings_entry(menu):
	"""The settings are a pane of that window, not a window of their own."""
	_, _, items = menu
	titles = [str(i.title()) for i in items]
	assert not any('Settings' in t for t in titles), titles


def test_the_window_entry_is_the_only_one_before_the_separator(menu):
	_, _, items = menu
	before = []
	for item in items:
		if item.isSeparatorItem():
			break
		before.append(str(item.title()))
	assert before == ['PolyKern UI'], before


def test_the_four_actions_are_still_there(menu):
	_, _, items = menu
	titles = [str(i.title()) for i in items if not i.isSeparatorItem()]
	assert titles == [
		'PolyKern UI',
		'Generate PolyKern Fingerprints for Selected Glyphs',
		'Generate PolyKern Fingerprints for Selected Glyphs in all Masters',
		'Clear PolyKern Sides of Selected Glyphs',
		'Clear PolyKern Sides of Selected Glyphs in all Masters',
	], titles


def test_the_all_masters_entries_are_still_option_alternates(menu):
	_, _, items = menu
	alternates = [str(i.title()) for i in items if i.isAlternate()]
	assert len(alternates) == 2, alternates
	assert all('all Masters' in t for t in alternates)
