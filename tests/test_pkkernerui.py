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
	for name in ('kernerPane', 'groupsPane', 'exportPane', 'settingsPane'):
		assert hasattr(plugin.w, name), name


def test_the_toolbar_offers_every_pane_with_the_export_held_out(window):
	"""The three that are part of kerning something sit together on the left;
	the experimental export is pushed to the far end by a flexible space."""
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert toolbar is not None, 'no toolbar'
	names = [str(i.itemIdentifier()) for i in toolbar.items()]
	assert names == [plugin.KERNER, plugin.GROUPS, plugin.SETTINGS,
			'NSToolbarFlexibleSpaceItem', plugin.EXPORT], names


def test_the_items_are_not_centred(window):
	"""`preference` centres them, which is what they were. `expanded` keeps
	the same two rows and puts them along the left."""
	from AppKit import NSWindowToolbarStyleExpanded, NSWindowToolbarStylePreference
	plugin, _ = window
	style = plugin.w.getNSWindow().toolbarStyle()
	assert style != NSWindowToolbarStylePreference, 'still centred'
	assert style == NSWindowToolbarStyleExpanded, style


def test_the_export_item_says_which_export_it_is(window):
	plugin, _ = window
	item = {str(i.itemIdentifier()): i for i in
			plugin.w.getNSWindow().toolbar().items()}[plugin.EXPORT]
	assert str(item.label()) == 'PK Export'


def test_the_item_set_cannot_be_saved_over(window):
	"""NSToolbar autosaves which items are in it, and a saved set WINS over
	the delegate's - which is how somebody who opened the two-item version
	would go on seeing two items. Nothing to save, nothing to restore."""
	plugin, _ = window
	toolbar = plugin.w.getNSWindow().toolbar()
	assert not toolbar.autosavesConfiguration()
	assert not toolbar.allowsUserCustomization()
	assert plugin.TOOLBAR_NAME != 'PolyKernPanes', 'the name the old set saved under'


def test_showing_one_pane_hides_the_rest(window):
	plugin, _ = window
	for which in (plugin.SETTINGS, plugin.EXPORT, plugin.KERNER, plugin.GROUPS):
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


def test_the_export_button_moved_with_it(window):
	plugin, _ = window
	assert hasattr(plugin.w.exportPane, 'exportButton')
	assert not hasattr(plugin.w.kernerPane, 'exportButton')
	assert plugin.w.exportPane.exportButton.getTitle() == 'Generate Bubbled Font'


def test_the_export_pane_is_laid_out(window):
	"""Its rules were written for a tab and are used in a pane now.

	THE BUTTON'S WIDTH IS NOT PINNED HERE, deliberately. Unconstrained it has
	no settled width - see the note on the rules - and this harness happens to
	resolve the ambiguity the flattering way every time, so an assertion about
	it would pass whether the width was stated or not."""
	plugin, _ = window
	plugin.showPane(plugin.EXPORT)
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	frame = plugin.w.exportPane.exportButton.getNSButton().frame()
	assert frame.size.width > 20 and frame.size.height > 10, frame


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
	assert 'Refer' in said, said


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
# The export writes a table nothing shipping reads yet. The pane said so in a
# paragraph, which is a thing read once.


def _ribbonPane(plugin):
	return plugin.w.exportPane.getNSView()


def test_the_export_pane_carries_a_ribbon(window):
	plugin, _ = window
	ribbon = plugin.exportRibbon
	assert ribbon is not None
	assert type(ribbon).__name__ == 'PKRibbonView'
	assert ribbon._word == 'BETA'


def test_it_sits_in_the_top_right_corner(window):
	plugin, _ = window
	plugin.showPane(plugin.EXPORT)
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	pane = _ribbonPane(plugin)
	frame = plugin.exportRibbon.frame()
	assert frame.origin.x + frame.size.width == pytest.approx(
			pane.frame().size.width), 'not against the right edge'
	high = (frame.origin.y if pane.isFlipped()
			else pane.frame().size.height - (frame.origin.y + frame.size.height))
	assert high == pytest.approx(0), f'{high} points down from the top'


def test_it_is_drawn_over_everything_the_rules_placed(window):
	plugin, _ = window
	assert list(_ribbonPane(plugin).subviews())[-1] is plugin.exportRibbon


def test_it_does_not_swallow_clicks(window):
	"""It lies over the corner of a pane and answers to nothing."""
	plugin, _ = window
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


def test_the_caption_is_wide_enough_not_to_wrap(window):
	"""It is written in lines that are meant to stay lines - numbered steps,
	and a Terminal command that reads badly broken in half. Lengthen the text
	past the box and it wraps with nothing said about it."""
	plugin, _ = window
	field = plugin.w.exportPane.caption.getNSTextField()
	natural = field.cell().cellSizeForBounds_(((0, 0), (10000, 10000))).width
	assert plugin.CAPTION_WIDTH >= natural, f'{natural:.0f} into {plugin.CAPTION_WIDTH}'
	assert plugin.CAPTION_WIDTH < plugin.WINDOW_SIZE[0] - 100, 'no room either side'


def test_the_caption_and_the_buttons_are_spaced_apart(window):
	"""They shared a pair of spacers, which cannot hold two different widths
	at once: something has to give, and what gives is the pair being equal -
	so the buttons come out off to one side."""
	plugin, _ = window
	plugin.showPane(plugin.EXPORT)
	plugin.w.getNSWindow().contentView().layoutSubtreeIfNeeded()
	pane = plugin.w.exportPane.getNSView().frame()
	for name in ('caption', 'exportButton', 'getHTMLButton'):
		control = getattr(plugin.w.exportPane, name)._nsObject
		frame = control.frame()
		middle = frame.origin.x + frame.size.width / 2.0
		assert middle == pytest.approx(pane.size.width / 2.0, abs=1.0), \
				f'{name} centred at {middle:.0f} of {pane.size.width:.0f}'
