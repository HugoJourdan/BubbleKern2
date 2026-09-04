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
	yield plugin, plugin.w.kernerPane.group0
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
	buttons = window[0].w.kernerPane.group1
	assert hasattr(buttons, 'applyButton')
	assert not hasattr(buttons, 'allButton') and not hasattr(buttons, 'selButton')
	assert buttons.applyButton.getTitle() == 'Apply Kerning'


def test_there_is_no_write_groups_switch_any_more(window):
	"""It is not optional now - PKCommonLogic sets useGroups True outright."""
	_, group = window
	assert not hasattr(window[0].w.kernerPane.group1, 'writeGroups')
	source = (RESOURCES / 'PKCommonLogic.py').read_text()
	assert 'useGroups = True' in source


def test_the_total_counts_only_the_ticked_rows(window):
	plugin, group = window
	group.permList.set([
		{'Kern': True, 'Left': 'A B', 'Right': 'x y', 'Add Flipped': False, 'Pairs': '4'},
		{'Kern': False, 'Left': 'T V W', 'Right': 'a e o', 'Add Flipped': False, 'Pairs': '9'},
	])
	plugin.refreshTotal()
	total = plugin.w.kernerPane.group1.total
	assert total.get().endswith('4'), total.get()


# --- where the total sits, and what it says ---------------------------------


def test_the_total_says_what_it_counts(window):
	plugin, _ = window
	assert plugin.w.kernerPane.group1.total.get().startswith('Total Pairs to Kern')


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
	bar = plugin.w.kernerPane.group1
	total = _visible(bar.total.getNSTextField())
	button = _visible(bar.applyButton.getNSButton())
	# the bar is not flipped, so higher on screen is a larger y
	assert total.origin.y >= button.origin.y + button.size.height, 'not above it'
	assert (abs((total.origin.x + total.size.width)
			- (button.origin.x + button.size.width)) < 2), 'not aligned right'


def test_the_total_and_the_button_are_not_touching(window):
	plugin, _ = window
	bar = plugin.w.kernerPane.group1
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
	bar = plugin.w.kernerPane.group1
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
	plugin.showRelevantPairs(plugin.w.kernerPane.group1.infoButton)
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
	plugin.showRelevantPairs(plugin.w.kernerPane.group1.infoButton)
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
	plugin.showRelevantPairs(plugin.w.kernerPane.group1.infoButton)
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


def test_every_pane_exists(window):
	plugin, _ = window
	for name in ('kernerPane', 'groupsPane', 'settingsPane'):
		assert hasattr(plugin.w, name), name


def test_the_export_is_not_a_pane_any_more(window):
	"""It is a sheet off the kerner's own button now, not a place you can be
	standing when you meant to be kerning."""
	plugin, _ = window
	assert not hasattr(plugin.w, 'exportPane')
	assert set(plugin.paneGroups()) == {plugin.KERNER, plugin.GROUPS,
			plugin.SETTINGS}, plugin.paneGroups().keys()


def test_the_toolbar_holds_the_settings_out_to_the_right(window):
	"""The two that are the work itself sit together on the left; the
	settings are what you go and change and come back from."""
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert toolbar is not None, 'no toolbar'
	names = [str(i.itemIdentifier()) for i in toolbar.items()]
	assert names == [plugin.KERNER, plugin.GROUPS,
			'NSToolbarFlexibleSpaceItem', plugin.SETTINGS], names


def test_the_items_are_not_centred(window):
	"""`preference` centres them, which is what they were. `expanded` keeps
	the same two rows and puts them along the left."""
	from AppKit import NSWindowToolbarStyleExpanded, NSWindowToolbarStylePreference
	plugin, _ = window
	style = plugin.w.getNSWindow().toolbarStyle()
	assert style != NSWindowToolbarStylePreference, 'still centred'
	assert style == NSWindowToolbarStyleExpanded, style


def test_the_toolbar_has_no_export_item(window):
	"""A toolbar item is standing furniture. This one stood out past every
	other one, for an experiment two buttons wide."""
	plugin, _ = window
	items = plugin.w.getNSWindow().toolbar().items()
	assert 'export' not in [str(i.itemIdentifier()) for i in items]
	labels = [str(i.label()) for i in items]
	assert not [l for l in labels if 'Export' in l], labels


def test_the_item_set_cannot_be_saved_over(window):
	"""NSToolbar autosaves which items are in it, and a saved set WINS over
	the delegate's - which is how somebody who opened the two-item version
	would go on seeing two items. Nothing to save, nothing to restore."""
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert not toolbar.autosavesConfiguration()
	assert not toolbar.allowsUserCustomization()
	assert plugin.TOOLBAR_NAME not in ('PolyKernPanes', 'PolyKernPanes.4'), \
			'a name an older, differently-sized set has already saved under'


def test_showing_one_pane_hides_the_rest(window):
	plugin, _ = window
	for which in (plugin.SETTINGS, plugin.KERNER, plugin.GROUPS):
		plugin.showPane(which)
		for identifier, pane in plugin.paneGroups().items():
			hidden = pane.getNSView().isHidden()
			assert hidden == (identifier != which), f'{identifier} showing {which}'


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


# --- the settings laid out for this window ---------------------------------


def _controlFrames(pane):
	"""Every placed control on a pane. -> [(name, NSRect)]"""
	out = []
	for name in dir(pane):
		if name.startswith('_'):
			continue
		holder = getattr(pane, name, None)
		view = getattr(holder, '_nsObject', None)
		if view is not None and hasattr(view, 'frame'):
			out.append((name, view.frame()))
	return out


def test_the_preview_fills_its_box(withTool):
	"""It was built at a flat 670 - the old window less its margins - and an
	autoresizing mask only acts on LATER resizes, so it drew 670 points of
	preview in an 816 point box and left the rest empty."""
	plugin, tool = withTool
	box = plugin.w.settingsPane.previewBox.getNSView().frame()
	view = tool.previewView.frame()
	assert view.size.width == pytest.approx(box.size.width, abs=1)
	assert view.size.height == pytest.approx(box.size.height, abs=1)


def test_the_preview_got_the_room_the_taller_window_gave(withTool):
	plugin, tool = withTool
	assert tool.PREVIEW_HEIGHT > 190, "still sized for the 398 point window"


def test_nothing_hangs_off_the_bottom_of_the_pane(withTool):
	"""The pane is not flipped, so a low y is near the bottom."""
	plugin, _ = withTool
	for name, frame in _controlFrames(plugin.w.settingsPane):
		assert frame.origin.y >= 0, f"{name} hangs off the bottom"


def test_nothing_runs_off_the_top(withTool):
	plugin, _ = withTool
	high = plugin.w.settingsPane.getNSView().frame().size.height
	for name, frame in _controlFrames(plugin.w.settingsPane):
		assert frame.origin.y + frame.size.height <= high + 1, f"{name} runs off"


def test_the_settings_use_the_height_they_have(withTool):
	"""They filled 398 points of a 500 point pane and left a hole. Whatever
	sits lowest should be near the bottom, not a hundred points above it."""
	plugin, _ = withTool
	frames = _controlFrames(plugin.w.settingsPane)
	lowest = min(f.origin.y for _, f in frames)
	assert lowest <= 40, f"{lowest} points of nothing under the last control"
	assert lowest >= 10, f"only {lowest} points of margin"


def test_the_title_is_not_the_old_name(withTool):
	plugin, _ = withTool
	assert plugin.w.settingsPane.shapeTitle.get() == 'PolyKern Parameters'


def test_the_two_ways_in_place_things_identically(withTool):
	"""The pane and the standalone fallback both go through buildSettings, so
	the numbers cannot drift apart."""
	source = (RESOURCES / 'PKTool.py').read_text()
	assert source.count('def buildSettings') == 1
	assert 'self.buildSettings(w)' in source
	kerner_source = (RESOURCES / 'PKKerner.py').read_text()
	assert 'tool.buildSettings(pane)' in kerner_source
	assert 'buildShapeSection' not in kerner_source, 'the kerner still places controls'


# --- The export pane, out of the kerner's tabs -------------------------------
# It was the second tab of a tab view inside the kerner pane, which put a tab
# bar inside a pane picker and made an experimental font export look like the
# second step of kerning. What is pinned here is that the tab view is gone and
# that what was in it is still reachable.


def test_the_tab_view_is_gone(window):
	plugin, _ = window
	assert not hasattr(plugin.w.kernerPane, 'tabs'), 'the tab view is still there'
	assert 'vanilla.Tabs' not in (RESOURCES / 'PKKerner.py').read_text()


def test_the_kerning_controls_are_straight_in_the_pane(window):
	plugin, group = window
	assert plugin.w.kernerPane.group0 is group
	assert hasattr(plugin.w.kernerPane, 'group1')


# --- The export, moved in beside the kerning ---------------------------------
# It was a pane of the window, picked from a toolbar item held out past every
# other one. It is a button on the kerning pane now, and a sheet over it.


@pytest.fixture
def exportSheet(window):
	"""The export sheet, up on the kerner window. -> (plugin, sheet)"""
	plugin, _ = window
	plugin.openExportSheet()
	# `openExportSheet` catches and logs, so a sheet that failed to build
	# leaves this at the class default rather than raising out here.
	assert plugin.exportW is not None, 'the sheet never went up'
	plugin.exportW.getNSWindow().contentView().layoutSubtreeIfNeeded()
	yield plugin, plugin.exportW
	plugin.closeExportSheet()


def _visual(button):
	"""A button's frame is bigger than the button: the bezel and the focus
	ring are drawn inside it. What is on screen is the alignment rect."""
	native = button.getNSButton()
	return native.alignmentRectForFrame_(native.frame())


def test_the_kerning_pane_offers_the_export(window):
	plugin, _ = window
	button = plugin.w.kernerPane.group1.exportButton
	assert button.getTitle() == 'PK Export…', button.getTitle()


def test_it_sits_beside_the_button_that_kerns(window):
	"""Next to Apply Kerning, on the same line and to its left - the export
	comes after the kerning, and reads left to right."""
	plugin, _ = window
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	group = plugin.w.kernerPane.group1
	export, applies = _visual(group.exportButton), _visual(group.applyButton)
	assert export.origin.x + export.size.width <= applies.origin.x + 1, \
			'sitting on the button that kerns'
	assert export.origin.y == pytest.approx(applies.origin.y, abs=1.0), \
			'not on the same line'
	assert export.size.height == pytest.approx(applies.size.height, abs=1.0), \
			'not the same height'


def test_it_does_not_sit_on_the_progress_bar(window):
	plugin, _ = window
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	group = plugin.w.kernerPane.group1
	bar = group.progress._nsObject.frame()
	export = _visual(group.exportButton)
	assert bar.origin.x + bar.size.width <= export.origin.x + 1, 'overlapping'


def test_pressing_it_puts_the_sheet_up(window):
	plugin, _ = window
	assert plugin.exportW is None, 'up before anybody asked'
	plugin.w.kernerPane.group1.exportButton.getNSButton().performClick_(None)
	try:
		assert plugin.exportW is not None, 'nothing came up'
	finally:
		plugin.closeExportSheet()


def test_the_sheet_holds_what_the_pane_held(exportSheet):
	plugin, sheet = exportSheet
	assert sheet.generateButton.getTitle() == 'Generate Bubbled Font'
	assert sheet.getHTMLButton.getTitle() == 'Get HTML tester'
	assert sheet.getHTMLButton.getNSButton().isEnabled(), 'greyed out'
	assert sheet.caption.get() == plugin.EXPORT_CAPTION


def test_the_sheet_can_be_got_out_of(exportSheet):
	"""A pane is left by picking another one; a sheet has to offer its own
	way out. Escape is the other one - see `escapableSheet`."""
	plugin, sheet = exportSheet
	assert sheet.closeButton.getTitle() == 'Close'
	assert isinstance(sheet, kerner.escapableSheet)


def test_the_return_key_does_not_export_a_font(exportSheet):
	"""The default button is the way out, not the action. Exporting a font is
	not a thing to set off on the way past."""
	plugin, sheet = exportSheet
	default = sheet.getNSWindow().defaultButtonCell()
	assert default is not None, 'no default button'
	assert default is sheet.closeButton.getNSButton().cell()


def test_everything_on_the_sheet_is_on_the_sheet(exportSheet):
	"""It is sized round its contents, so there is nothing to absorb a row
	that grew: anything added has to be measured back in here."""
	plugin, sheet = exportSheet
	view = sheet.getNSWindow().contentView()
	size = view.frame().size
	for name in ('caption', 'generateButton', 'getHTMLButton', 'closeButton'):
		frame = getattr(sheet, name)._nsObject.frame()
		assert frame.origin.y >= -1, f'{name} off the bottom'
		assert frame.origin.y + frame.size.height <= size.height + 1, \
				f'{name} off the top of {size.height}'
		assert frame.origin.x >= -1, f'{name} off the left'
		assert frame.origin.x + frame.size.width <= size.width + 1, \
				f'{name} off the right of {size.width}'


def test_the_rows_do_not_sit_on_one_another(exportSheet):
	"""A sheet's content view is NOT flipped, so the lower control has the
	smaller y."""
	plugin, sheet = exportSheet
	order = ('caption', 'generateButton', 'getHTMLButton', 'closeButton')
	for upper, lower in zip(order, order[1:]):
		over = getattr(sheet, upper)._nsObject.frame()
		under = getattr(sheet, lower)._nsObject.frame()
		assert under.origin.y + under.size.height <= over.origin.y + 1, \
				f'{lower} is on top of {upper}'


def test_the_caption_is_given_the_height_it_needs(exportSheet):
	"""The sheet is sized round the paragraph, so the paragraph's box has to
	be the size the paragraph actually comes to."""
	plugin, sheet = exportSheet
	field = sheet.caption.getNSTextField()
	needs = field.cell().cellSizeForBounds_(
			((0, 0), (plugin.CAPTION_WIDTH, 10000))).height
	assert plugin.CAPTION_HEIGHT >= needs, f'{needs:.0f} into {plugin.CAPTION_HEIGHT}'
	assert plugin.EXPORT_SHEET_SIZE[0] >= plugin.CAPTION_WIDTH + 40, 'no margins'


def test_the_kerning_pane_keeps_a_top_margin(window):
	"""The tab view used to inset what it held; nothing does now."""
	plugin, group = window
	pane = plugin.w.kernerPane.getNSView()
	popup = group.optionsPopup.getNSPopUpButton()
	top = pane.convertRect_fromView_(popup.frame(), popup.superview())
	high = pane.frame().size.height - (top.origin.y + top.size.height)
	assert high >= 6, f'only {high} points above the popup'


# --- The groups pane ---------------------------------------------------------


def test_the_groups_pane_holds_the_grid(window):
	plugin, _ = window
	assert hasattr(plugin.w.groupsPane, 'caption')
	document = plugin.w.groupsPane.groups.getNSScrollView().documentView()
	assert document is plugin.groupGrid
	assert type(document).__name__ == 'PKGroupGridView'


def test_visiting_the_groups_pane_reads_the_font_again(window, monkeypatch):
	"""References are written while this window is open, so once at build
	time is not enough."""
	plugin, _ = window
	seen = []
	monkeypatch.setattr(plugin, 'refreshGroups', lambda: seen.append(1),
			raising=False)
	plugin.showPane(plugin.KERNER)
	assert seen == []
	plugin.showPane(plugin.GROUPS)
	assert seen == [1]


def test_a_font_with_no_references_says_so(window):
	plugin, _ = window
	master = types.SimpleNamespace(id='m1', name='Regular')
	Glyphs.font.selectedFontMaster = master
	plugin.showPane(plugin.GROUPS)
	said = plugin.w.groupsPane.caption.get()
	assert 'PolyKern Group' in said, said
	assert 'Refer' not in said and 'Kerning Key' not in said, 'the old wording'


def test_with_no_font_the_pane_says_that_instead(window, monkeypatch):
	plugin, _ = window
	monkeypatch.setattr(Glyphs, 'font', None, raising=False)
	monkeypatch.setattr(plugin, 'font', None, raising=False)
	plugin.showPane(plugin.GROUPS)
	assert plugin.w.groupsPane.caption.get() == 'Open a font to see its groups.'


def test_the_caption_counts_a_glyph_on_both_sides_once():
	"""A glyph can be in a left group and a right one and is still one glyph."""
	said = kerner.PolyKernKerner.groupsCaption(None, [
		{'name': 'o', 'members': ['o', 'c', 'e']},
		{'name': 'n', 'members': ['n', 'o', 'c']},
	])
	assert said.startswith('2 groups, 4 glyphs'), said


# --- The BETA ribbon ---------------------------------------------------------
# The export writes a table nothing shipping reads yet. The sheet says so in a
# paragraph, which is a thing read once.


def _ribbonView(sheet):
	return sheet.getNSWindow().contentView()


def test_the_export_sheet_carries_a_ribbon(exportSheet):
	plugin, _ = exportSheet
	ribbon = plugin.exportRibbon
	assert ribbon is not None
	assert type(ribbon).__name__ == 'PKRibbonView'
	assert ribbon._word == 'BETA'


def test_it_sits_in_the_top_right_corner(exportSheet):
	plugin, sheet = exportSheet
	view = _ribbonView(sheet)
	frame = plugin.exportRibbon.frame()
	assert frame.origin.x + frame.size.width == pytest.approx(
			view.frame().size.width), 'not against the right edge'
	high = (frame.origin.y if view.isFlipped()
			else view.frame().size.height - (frame.origin.y + frame.size.height))
	assert high == pytest.approx(0), f'{high} points down from the top'


def test_it_is_drawn_over_everything_else(exportSheet):
	plugin, sheet = exportSheet
	assert list(_ribbonView(sheet).subviews())[-1] is plugin.exportRibbon


def test_it_does_not_swallow_clicks(exportSheet):
	"""It lies over the corner of the sheet and answers to nothing."""
	plugin, _ = exportSheet
	ribbon = plugin.exportRibbon
	middle = ribbon.frame()
	assert ribbon.hitTest_((middle.origin.x + 4, middle.origin.y + 4)) is None


def test_the_word_fits_on_the_band():
	"""The band's centre line is what there is to write on. Raise the type
	size or lengthen the word and it runs off both ends without a sound."""
	from AppKit import (NSAttributedString, NSColor, NSFont, NSFontAttributeName,
			NSFontWeightBold, NSForegroundColorAttributeName, NSKernAttributeName)
	# UNDER ITS PLAIN NAME: PKKerner imported it that way, and executing the
	# file twice re-registers the ObjC class in it.
	ribbon = _load('PKRibbon', 'PKRibbon')
	assert ribbon.RIBBON_OUTER < ribbon.RIBBON_SIZE, 'the band runs off the view'
	centre = (ribbon.RIBBON_INNER + ribbon.RIBBON_OUTER) / 2.0
	along = centre * (2 ** 0.5)
	label = NSAttributedString.alloc().initWithString_attributes_('BETA', {
		NSFontAttributeName: NSFont.systemFontOfSize_weight_(
			ribbon.RIBBON_TEXT, NSFontWeightBold),
		NSForegroundColorAttributeName: NSColor.blackColor(),
		NSKernAttributeName: ribbon.RIBBON_TRACKING,
	})
	assert label.size().width < along - 8, f'{label.size().width} on {along}'
	# AND THE BAND IS THICK ENOUGH FOR IT, measured across rather than along.
	thickness = (ribbon.RIBBON_OUTER - ribbon.RIBBON_INNER) / (2 ** 0.5)
	assert thickness > label.size().height, f'{thickness} for {label.size().height}'


def test_the_caption_is_wide_enough_not_to_wrap(exportSheet):
	"""It is written in lines that are meant to stay lines - numbered steps,
	and a Terminal command that reads badly broken in half. Lengthen the text
	past the box and it wraps with nothing said about it."""
	plugin, sheet = exportSheet
	field = sheet.caption.getNSTextField()
	natural = field.cell().cellSizeForBounds_(((0, 0), (10000, 10000))).width
	assert plugin.CAPTION_WIDTH >= natural, f'{natural:.0f} into {plugin.CAPTION_WIDTH}'
	assert plugin.EXPORT_SHEET_SIZE[0] == plugin.CAPTION_WIDTH + 40, \
			'the sheet is no longer sized round the paragraph'


def test_the_two_buttons_are_centred_under_it(exportSheet):
	"""They shared a pair of spacer views with the caption once, which cannot
	hold two different widths at once: what gave was the pair being equal, and
	the buttons came out off to one side. The sheet places them by hand."""
	plugin, sheet = exportSheet
	width = sheet.getNSWindow().contentView().frame().size.width
	for name in ('generateButton', 'getHTMLButton'):
		frame = getattr(sheet, name)._nsObject.frame()
		middle = frame.origin.x + frame.size.width / 2.0
		assert middle == pytest.approx(width / 2.0, abs=1.0), \
				f'{name} centred at {middle:.0f} of {width:.0f}'


# --- Set Refer Glyphs Automatically, moved -----------------------------------
# It made the groups from an item in the settings pane's action menu, two panes
# away from the grid that shows what it did.


def test_the_groups_pane_offers_the_command(window):
	plugin, _ = window
	button = plugin.w.groupsPane.autoButton
	assert button.getTitle() == 'Auto-generate PolyKern Groups'


def test_the_button_is_wide_enough_for_its_own_title(window):
	"""A vanilla Button truncates rather than growing, and a truncated
	command is one nobody presses."""
	plugin, _ = window
	native = plugin.w.groupsPane.autoButton.getNSButton()
	natural = native.cell().cellSize().width
	assert plugin.AUTO_BUTTON_W >= natural, f'{natural:.0f} into {plugin.AUTO_BUTTON_W}'


def test_the_caption_does_not_run_under_the_button(window):
	plugin, _ = window
	plugin.showPane(plugin.GROUPS)
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	caption = plugin.w.groupsPane.caption._nsObject.frame()
	button = plugin.w.groupsPane.autoButton.getNSButton().frame()
	assert caption.origin.x + caption.size.width <= button.origin.x + 1


def test_the_settings_menu_has_let_it_go(withTool):
	plugin, tool = withTool
	titles = [title for title, _ in tool.actionMenuItems()]
	assert not [t for t in titles if t and 'Refer Glyphs' in t], titles
	assert not [t for t in titles if t and 'PolyKern Groups' in t], titles
	assert 'Set Bubble Settings based on Kerning…' in titles, 'took the wrong one'


def test_without_a_tool_the_button_says_so_rather_than_doing_nothing(window,
		monkeypatch):
	plugin, _ = window
	said = []
	monkeypatch.setattr(kerner.PKCommonLogic, 'show_alert',
			lambda *a, **k: said.append(a), raising=False)
	plugin.setPolyKernGroups()
	assert said, 'silently did nothing'


# --- The sheets those commands put up ----------------------------------------
# `setW` was a window and is a pane now. vanilla.Sheet reaches into its parent
# for `_window`, a Group has none, and every caller catches the AttributeError
# and logs it - so all three sheets stopped appearing and nothing said why.


def test_a_sheet_can_be_put_up_on_the_pane(withTool):
	import vanilla
	plugin, tool = withTool
	parent = tool.sheetParent()
	assert parent is not None, 'nothing to hang a sheet on'
	assert parent is plugin.w.getNSWindow()
	sheet = vanilla.Sheet((240, 130), parent)  # this is what used to raise
	assert sheet is not None


def test_the_pane_itself_is_not_offered_as_a_parent(withTool):
	"""It is what `setW` holds, and it is exactly what does not work."""
	plugin, tool = withTool
	assert tool.setW is plugin.w.settingsPane
	assert tool.sheetParent() is not tool.setW


# --- Only the selected glyphs ------------------------------------------------
# A run over the selection is a run over a smaller font: it groups the chosen
# glyphs among themselves and does not so much as measure the rest.


def test_the_sheet_asks_whether_to_stay_in_the_selection(withTool):
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		assert hasattr(tool.autoW, 'onlySelected')
		assert tool.autoW.onlySelected.getTitle() == 'Selected glyphs only'
		assert not tool.autoW.onlySelected.get(), 'the whole font by default'
	finally:
		tool.closeAutoGroupWindow()


def test_the_sheet_still_fits_what_it_holds(withTool):
	"""It grew a row. Everything in it has to have come down with that."""
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		height = tool.autoW.getNSWindow().contentView().frame().size.height
		for name in ('source', 'sourceLabel', 'sides', 'sidesLabel',
				'overwrite', 'onlySelected', 'cancel', 'apply', 'report'):
			frame = getattr(tool.autoW, name)._nsObject.frame()
			assert frame.origin.y >= -1, f'{name} above the top'
			assert frame.origin.y + frame.size.height <= height + 1, \
					f'{name} runs off the bottom of {height}'
		# AND THE NEW ROW IS A ROW, not sitting on the one above it. A sheet's
		# content view is NOT flipped, so the lower control has the smaller y.
		over = tool.autoW.overwrite._nsObject.frame()
		only = tool.autoW.onlySelected._nsObject.frame()
		if tool.autoW.getNSWindow().contentView().isFlipped():
			assert only.origin.y >= over.origin.y + over.size.height, 'overlapping'
		else:
			assert only.origin.y + only.size.height <= over.origin.y, 'overlapping'
	finally:
		tool.closeAutoGroupWindow()


def test_asking_for_a_selection_that_is_empty_says_so(withTool, monkeypatch):
	"""Not "0 drawn, 0 grouped" after doing the work - and not doing it."""
	plugin, tool = withTool
	monkeypatch.setattr(Glyphs.font, 'selectedLayers', [], raising=False)
	measured = []
	monkeypatch.setattr(kerner.PKAutoBubble, 'auto_bubble_plan',
			lambda *a, **k: measured.append(1), raising=False)
	tool.openAutoGroupWindow()
	try:
		tool.autoW.onlySelected.set(True)
		tool.applyAutoGroup(None)
		assert tool.autoW.report.get() == 'Nothing is selected.'
		assert measured == [], 'measured the font anyway'
	finally:
		tool.closeAutoGroupWindow()


def test_the_names_a_run_may_look_at(withTool):
	"""None and an empty set are different answers: none is the whole font,
	empty is a selection that has nothing in it."""
	plugin, tool = withTool
	font = types.SimpleNamespace(selectedLayers=[])
	assert tool.autoGroupNames(font, False) is None
	assert tool.autoGroupNames(font, True) == set()


# --- The icons in the toolbar ------------------------------------------------


def test_every_item_has_an_icon_and_no_two_share_one(window):
	"""A symbol name that does not exist comes back None, and the item then
	shows a blank space rather than complaining."""
	plugin, _ = window
	images = {}
	for item in plugin.w.getNSWindow().toolbar().items():
		identifier = str(item.itemIdentifier())
		if identifier.startswith('NS'):
			continue  # the flexible space has nothing to show
		image = item.image()
		assert image is not None, f'{identifier} has no icon'
		images[identifier] = image
	assert len(set(id(i) for i in images.values())) == len(images), 'shared icon'


def test_the_symbol_names_are_real(window):
	"""imageWithSystemSymbolName_ answers None to a name it does not know, so
	a typo is a blank toolbar item and nothing else."""
	from AppKit import NSImage
	for name in ('gear', 'rectangle.stack.fill'):
		assert NSImage.imageWithSystemSymbolName_accessibilityDescription_(
				name, None) is not None, name


def test_the_kerner_wears_its_own_artwork(window):
	plugin, _ = window
	icon = plugin.kernerIcon()
	assert icon is not None, 'PK_KernerIcon.pdf did not load'
	assert (RESOURCES / plugin.KERNER_ICON).exists()


def test_the_artwork_is_sized_by_its_ink_not_its_page(window):
	"""The page is 38 points square with 4 of margin top and bottom. Handed
	over as it is, the mark would stand a tenth shorter than the symbols."""
	plugin, _ = window
	icon = plugin.kernerIcon()
	ink = _load('PKIcon', 'PKIcon').inkBounds(icon)
	assert ink.size.height == pytest.approx(plugin.KERNER_ICON_INK, abs=0.5), ink.size
	# AND LEVEL WITH WHAT IS BESIDE IT, which is the whole point of measuring.
	from AppKit import NSImage
	gear = NSImage.imageWithSystemSymbolName_accessibilityDescription_('gear', None)
	gearInk = _load('PKIcon', 'PKIcon').inkBounds(gear)
	assert abs(ink.size.height - gearInk.size.height) < 2.0, (ink.size, gearInk.size)


def test_a_missing_file_falls_back_rather_than_leaving_a_hole(window,
		monkeypatch):
	plugin, _ = window
	monkeypatch.setattr(plugin, 'KERNER_ICON', 'NoSuchIcon.pdf', raising=False)
	assert plugin.kernerIcon() is None


# --- Which road to a group ---------------------------------------------------
# A font that has been kerned already holds an answer to "which glyphs share a
# side". Measuring the shapes afresh proposes a second, different set of groups
# for the same font, so the sheet asks which one the run should follow.


def test_the_sheet_asks_which_road(withTool):
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		popup = tool.autoW.source
		assert list(popup.getItems()) == ['Shape detection',
				'Existing kerning groups']
		assert popup.get() == 0, 'shape detection is the one that always works'
	finally:
		tool.closeAutoGroupWindow()


def test_the_titles_and_the_meanings_cannot_drift(withTool):
	"""One tuple of pairs, not two parallel lists: parallel lists are one
	reordering away from offering "Shape detection" and running the other."""
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		offered = list(tool.autoW.source.getItems())
		assert offered == [title for title, _ in tool.AUTO_SOURCES]
		assert [key for _, key in tool.AUTO_SOURCES] == [
				kerner.PKAutoBubble.BY_SHAPE,
				kerner.PKAutoBubble.BY_KERNING_GROUPS]
	finally:
		tool.closeAutoGroupWindow()


def test_the_new_question_is_a_row_of_its_own(withTool):
	"""A sheet's content view is NOT flipped, so the upper control has the
	larger y."""
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		source = tool.autoW.source.getNSPopUpButton().frame()
		sides = tool.autoW.sides.getNSPopUpButton().frame()
		if tool.autoW.getNSWindow().contentView().isFlipped():
			assert source.origin.y + source.size.height <= sides.origin.y
		else:
			assert sides.origin.y + sides.size.height <= source.origin.y
	finally:
		tool.closeAutoGroupWindow()


def test_the_popup_is_wide_enough_for_its_longest_answer(withTool):
	"""A truncated answer is one nobody can tell from the other."""
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		native = tool.autoW.source.getNSPopUpButton()
		native.selectItemAtIndex_(1)  # 'Existing kerning groups', the long one
		assert native.cell().cellSize().width <= native.frame().size.width + 1, \
				f'{native.cell().cellSize().width:.0f} into {native.frame().size.width:.0f}'
	finally:
		tool.closeAutoGroupWindow()


def test_the_labels_are_wide_enough_for_themselves(withTool):
	plugin, tool = withTool
	tool.openAutoGroupWindow()
	try:
		for name in ('sourceLabel', 'sidesLabel'):
			native = getattr(tool.autoW, name)._nsObject
			assert native.cell().cellSize().width <= tool.AUTO_LABEL_W + 1, \
					f'{name} truncated'
	finally:
		tool.closeAutoGroupWindow()


class _KernGrouped:
	"""A glyph that is in a kerning group, as far as the run can tell."""

	def __init__(self, name, left=None, right=None):
		self.name = name
		self.leftKerningGroup = left
		self.rightKerningGroup = right


def _stubRun(tool, monkeypatch, glyphs=()):
	"""Everything applyAutoGroup leans on, canned. -> the kwargs the plan got"""
	seen = {}
	font = Glyphs.font
	monkeypatch.setattr(font, 'glyphs', list(glyphs), raising=False)
	monkeypatch.setattr(font, 'selectedFontMaster',
			types.SimpleNamespace(id='m1', name='Regular'), raising=False)
	monkeypatch.setattr(font, 'disableUpdateInterface', lambda: None, raising=False)
	monkeypatch.setattr(font, 'enableUpdateInterface', lambda: None, raising=False)
	auto = kerner.PKAutoBubble
	monkeypatch.setattr(auto, 'auto_settings', lambda f, m: {
			'gap': 20, 'step': 10, 'tolerance': 5, 'max_nodes': 8,
			'slope': 1.0, 'max_inset': 80, 'amplitude': 1.0}, raising=False)
	monkeypatch.setattr(auto, 'resolve_grid', lambda f, m: 0, raising=False)

	def plan(*a, **k):
		seen.update(k)
		return {auto.LEFT: {'nodes': {}, 'refer': {}},
				auto.RIGHT: {'nodes': {}, 'refer': {}}}

	monkeypatch.setattr(auto, 'auto_bubble_plan', plan, raising=False)
	monkeypatch.setattr(sys.modules['PKBubbleStore'], 'writePlan',
			lambda *a, **k: (0, 0, 0), raising=False)
	monkeypatch.setattr(tool, 'refreshAfterWrite', lambda: None, raising=False)
	monkeypatch.setattr(tool, 'refreshGroupsPane', lambda: None, raising=False)
	return seen


def test_the_answer_reaches_the_run(withTool, monkeypatch):
	plugin, tool = withTool
	seen = _stubRun(tool, monkeypatch, [
			_KernGrouped('n', left='n'), _KernGrouped('m', left='n')])
	tool.openAutoGroupWindow()
	try:
		tool.autoW.source.set(1)
		tool.applyAutoGroup(None)
		assert seen.get('source') == kerner.PKAutoBubble.BY_KERNING_GROUPS
	finally:
		tool.closeAutoGroupWindow()


def test_the_default_answer_reaches_it_too(withTool, monkeypatch):
	plugin, tool = withTool
	seen = _stubRun(tool, monkeypatch)
	tool.openAutoGroupWindow()
	try:
		tool.applyAutoGroup(None)
		assert seen.get('source') == kerner.PKAutoBubble.BY_SHAPE
	finally:
		tool.closeAutoGroupWindow()


def test_a_font_with_no_kerning_groups_is_told_before_it_is_measured(withTool,
		monkeypatch):
	"""Not a whole-font scan that produces nothing and says so afterwards."""
	plugin, tool = withTool
	seen = _stubRun(tool, monkeypatch, [_KernGrouped('n'), _KernGrouped('m')])
	tool.openAutoGroupWindow()
	try:
		tool.autoW.source.set(1)
		tool.applyAutoGroup(None)
		assert tool.autoW.report.get() == 'This font has no kerning groups.'
		assert not seen, 'measured the font anyway'
	finally:
		tool.closeAutoGroupWindow()


def test_a_group_of_one_is_not_something_to_run_on(withTool, monkeypatch):
	"""Every glyph in a group by itself is a font with no groups in it."""
	plugin, tool = withTool
	seen = _stubRun(tool, monkeypatch, [
			_KernGrouped('n', left='n'), _KernGrouped('o', left='o')])
	tool.openAutoGroupWindow()
	try:
		tool.autoW.source.set(1)
		tool.applyAutoGroup(None)
		assert tool.autoW.report.get() == 'This font has no kerning groups.'
		assert not seen
	finally:
		tool.closeAutoGroupWindow()


def test_the_summary_says_which_road_it_took(withTool, monkeypatch):
	"""It is also the heading of the results sheet, and "42 grouped" means a
	different thing depending on who decided the groups."""
	plugin, tool = withTool
	_stubRun(tool, monkeypatch, [
			_KernGrouped('n', left='n'), _KernGrouped('m', left='n')])
	tool.openAutoGroupWindow()
	try:
		tool.autoW.source.set(1)
		tool.applyAutoGroup(None)
		assert 'from kerning groups' in tool.autoW.report.get()
		tool.autoW.source.set(0)
		tool.applyAutoGroup(None)
		assert 'by shape' in tool.autoW.report.get()
	finally:
		tool.closeAutoGroupWindow()
