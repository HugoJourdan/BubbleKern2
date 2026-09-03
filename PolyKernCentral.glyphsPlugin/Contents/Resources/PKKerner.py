from __future__ import division, print_function, unicode_literals

import objc
from GlyphsApp import Glyphs, GSLayer, GSGlyph, GetFolder, EDIT_MENU, UPDATEINTERFACE #, GSCallbackHandler
from GlyphsApp.plugins import GeneralPlugin
import traceback
import vanilla
import subprocess # for revealing exported font in Finder
import re  # for displaying font file name
import time # for managing progress bar
from typing import Optional, Any
from Foundation import NSMutableDictionary, NSOperationQueue #, NSLog

from AppKit import (
	NSMenu,  # for the PolyKern submenu
	NSMenuItem,
	NSEventModifierFlagOption,  # for the all-masters variant of a menu item
	NSImage,  # for setting plus and minus button image
	NSFont,  # for setting preview in Menlo
	# NSDragOperationMove,  # currently useless
	NSFloatingWindowLevel,
	NSWorkspace,  # for revealing exported fonts in Finder
	NSURL,  # for revealing exported fonts in Finder
	NSLayoutConstraint,  # to sit the add and delete buttons on the list
	NSAttributedString,  # to measure a paragraph before giving it a box
	NSFontAttributeName,
	NSStringDrawingUsesLineFragmentOrigin,
	NSViewWidthSizable,  # to keep the group grid as wide as it is scrolled in
	NSToolbarFlexibleSpaceItemIdentifier,  # to hold the export item out right
)
from Foundation import NSMakeRect, NSMakeSize

import PKAutoBubble
import PKBubbleStore as store
import PKCommonLogic
import PKExport
import PKIcon
import PKRibbon
from PKGroupGrid import PKGroupGridView

totalPairsPrefix = 'Total Pairs to Kern : '

# THE LIVE PLUGIN, so the tool can find the window the settings now live in.
# Mirrors `PKTool.mainDrawingHandler`, which is how this plugin finds the tool.
# The two are separate principal classes of one bundle and Glyphs makes both.
mainKerner = None

# Vanilla.Sheet which can be closed upon esc key press
class escapableSheet(vanilla.Sheet):
	def cancelOperation_(self, sender):
		# called when Escape is pressed
		self.close()

# PLUGIN WITH A WINDOW UNDER EDIT TOOL
# 1. GENERATES PRE-COMPUTED KERNING DATA (MOST COMMON USE CASE)
# 2. GENERATES FONT WITH BBLH AND BBLV TABLES (EXPERIMENTAL)
# 3. REMOVES BUBBLE DATA ENTIRELY

# THE BACKEND CODE FOR COMPUTING BUBBLE SHAPES SHOULD BE SHARED WITH THE DRAWING METHODS (IN PKCOMMONLOGIC)


popupOptions = ["New Preset...", "Rename Selected...", "Duplicate Selected...", "Delete Selected..."]

Menlo12 = NSFont.fontWithName_size_("Menlo", 12)


# INITIATE LOGGING
import logging
import os

def _setup_logger():
	logger = logging.getLogger("PolyKern")

	if logger.handlers:
		return logger  # already configured (important for Glyphs reload)

	logger.setLevel(logging.DEBUG)
	log_path = os.path.expanduser("~/Desktop/Glyphs_PolyKern.log")
	handler = logging.FileHandler(log_path)
	formatter = logging.Formatter("%(asctime)s PolyKern: %(message)s")
	handler.setFormatter(formatter)
	logger.addHandler(handler)
	logger.propagate = False  # prevents double logging
	return logger

def log(message:str = '', error: bool = None):
	level = logging.ERROR if error is None else logging.DEBUG
	_setup_logger().log(level, message)

# / INITIATE LOGGING

class PolyKernKerner(GeneralPlugin):
	name: str
	w: Optional[vanilla.Window] = None

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize({
			'en': 'PolyKern Kerner…',
			'ja': 'PolyKern ダイアログ…'
		})

	@objc.python_method
	def start(self):  # STUFF TO UPON GLYPHS STARTUP
		global mainKerner
		mainKerner = self
		# BEFORE ANYTHING READS A PREFERENCE. This plugin was called BubbleKern
		# and everything it remembers was saved under that name; the first
		# launch under the new one brings it over. Runs once, and says so in
		# the log when it moved anything.
		try:
			moved = PKAutoBubble.migrate_preferences()
			if moved:
				PKCommonLogic.log(f'carried {moved} preferences over from BubbleKern')
		except Exception:
			PKCommonLogic.log(f'preference migration failed: {traceback.format_exc()}',
				error=True)
		Glyphs.menu[EDIT_MENU].append(self.buildMenu())
		self.registerParameterSheet()

	MENU_TITLE = 'PolyKern UI'

	@objc.python_method
	def buildMenu(self):
		"""The Edit > PolyKern submenu. -> NSMenuItem

		ITS OWN METHOD so it can be built and read without a running Glyphs;
		`start` only hangs it on the menu bar.
		"""
		submenu = NSMenu.alloc().initWithTitle_('PolyKern')
		# ONE ENTRY FOR THE WINDOW, because there is one window. The kerner and
		# the settings were two of these when they were two windows.
		window = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			self.MENU_TITLE, self.showWindow_, '')
		window.setTarget_(self)
		submenu.addItem_(window)
		submenu.addItem_(NSMenuItem.separatorItem())

		generate = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Generate PolyKern Fingerprints for Selected Glyphs',
			self.generateSelected_, '')
		generate.setTarget_(self)
		submenu.addItem_(generate)
		# THE OPTION VARIANT. An alternate takes the place of the item above it
		# while its modifier is held: same key equivalent, different mask.
		everyMaster = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Generate PolyKern Fingerprints for Selected Glyphs in all Masters',
			self.generateAllMasters_, '')
		everyMaster.setTarget_(self)
		everyMaster.setKeyEquivalentModifierMask_(NSEventModifierFlagOption)
		everyMaster.setAlternate_(True)
		submenu.addItem_(everyMaster)

		clear = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Clear PolyKern Sides of Selected Glyphs', self.clearSelected_, '')
		clear.setTarget_(self)
		submenu.addItem_(clear)
		clearEverywhere = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Clear PolyKern Sides of Selected Glyphs in all Masters',
			self.clearAllMasters_, '')
		clearEverywhere.setTarget_(self)
		clearEverywhere.setKeyEquivalentModifierMask_(NSEventModifierFlagOption)
		clearEverywhere.setAlternate_(True)
		submenu.addItem_(clearEverywhere)

		parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'PolyKern', None, '')
		parent.setSubmenu_(submenu)
		return parent

	def registerParameterSheet(self):
		# THE SETTINGS PARAMETER GETS ITS OWN EDITOR. Clicking its value in Font
		# Info opens sliders instead of a text field; the string stays editable
		# by hand for anyone who prefers that.
		try:
			from GlyphsApp import GSCallbackHandler
			import PKAutoBubble
			import PKParameterSheet
			GSCallbackHandler.addCustomParameterSheetController_forParameter_(
				PKParameterSheet.PolyKernParameterSheet,
				PKAutoBubble.SETTINGS_PARAMETER)
		except Exception:
			PKCommonLogic.log(
				f'PolyKern parameter sheet not registered: {traceback.format_exc()}',
				error=True)

	def openSettings_(self, sender):
		# THE SAME WINDOW AS THE KERNER, opened on its other pane. The settings
		# used to be a window of the tool's own; the pane is still the tool's,
		# and says so itself when the tool has not loaded.
		try:
			self.showWindow_(sender)
			if self.w is not None:
				self.showPane(self.SETTINGS)
		except Exception:
			PKCommonLogic.log(f'openSettings error: {traceback.format_exc()}', error=True)

	def generateSelected_(self, sender):
		self.generateSoon(False)

	def generateAllMasters_(self, sender):
		self.generateSoon(True)

	def clearSelected_(self, sender):
		self.clearSoon(False)

	def clearAllMasters_(self, sender):
		self.clearSoon(True)

	@objc.python_method
	def clearSoon(self, allMasters):
		# SAME REASON AS generateSoon: this puts an alert up, and raising one
		# while AppKit is still taking the menu down deadlocks.
		def run():
			self.clearSides(allMasters)
		NSOperationQueue.mainQueue().addOperationWithBlock_(run)

	@objc.python_method
	def selectedLayers(self, allMasters):
		"""The layers a menu command works on. -> list

		ONE PER SELECTED GLYPH, not per selected layer: the same glyph can sit
		in a tab twice, and doing it twice is at best wasted work.
		"""
		font = Glyphs.font
		if font is None:
			return []
		glyphs, seen = [], set()
		for layer in font.selectedLayers:
			glyph = layer.parent if isinstance(layer, GSLayer) else None
			if glyph is not None and glyph.name not in seen:
				seen.add(glyph.name)
				glyphs.append(glyph)
		masters = font.masters if allMasters else [font.selectedFontMaster]
		layers = [glyph.layers[master.id] for glyph in glyphs for master in masters]
		return [layer for layer in layers
			if layer is not None and layer.name is not None]

	@objc.python_method
	def clearSides(self, allMasters):
		"""Take PolyKern's data off the selected glyphs, both sides."""
		try:
			import PKBubbleStore
			import PKTool
			layers = self.selectedLayers(allMasters)
			if not layers:
				return
			where = 'any master' if allMasters else 'this master'
			carried = PKBubbleStore.countCarried(layers)
			if not carried:
				PKCommonLogic.show_alert('Nothing to Clear',
					f'The selected glyphs carry no PolyKern data in {where}.',
					cancel=False)
				return
			sides = 'side' if carried == 1 else 'sides'
			# CANCEL FIRST, so Return cancels. Same reasoning as
			# `askAboutExisting`, and it matters more here: there is no answer
			# to this question that does less damage than not answering it.
			answer = PKCommonLogic.ask_choice(
				f'Clear {carried} PolyKern {sides}?',
				f'The wall, any reference to another glyph, any mirror of the '
				f'other side and the auto flag all go, across '
				f'{"every master" if allMasters else "the current master"}. '
				f'This can be undone.',
				('Cancel', f'Clear {carried} {sides.title()}'))
			if answer != 1:
				return
			PKBubbleStore.clearBubbles(layers)
			if PKTool.mainDrawingHandler is not None:
				PKTool.mainDrawingHandler.refreshAfterWrite()
		except Exception:
			PKCommonLogic.log(f'clearSides error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def generateSoon(self, allMasters):
		# ONE TURN OF THE RUN LOOP LATER. The run can put an alert up now, and
		# a modal window raised while AppKit is still taking the menu down is
		# the deadlock this codebase keeps meeting. See `soon` in PKTool.
		def run():
			self.generateBubbles(allMasters)
		NSOperationQueue.mainQueue().addOperationWithBlock_(run)

	# WHAT THE QUESTION CAN COME BACK WITH.
	OVERWRITE, KEEP, CANCEL = 'overwrite', 'keep', 'cancel'

	@objc.python_method
	def askAboutExisting(self, count):
		"""Whether to write over the sides that already hold work. -> str

		BUTTON ORDER IS THE MACOS ONE: the first added sits rightmost and is
		what Return presses, and AppKit gives a button titled `Cancel` the
		escape key by itself. So `Keep Them` is first - it is the answer that
		loses nothing and still does the work asked for, which is what a Return
		pressed without reading should do - and overwriting has to be aimed at.
		"""
		sides = 'side' if count == 1 else 'sides'
		answer = PKCommonLogic.ask_choice(
			f'Overwrite {count} PolyKern {sides}?',
			f'{count} of the selected {sides} {"was" if count == 1 else "were"} '
			'drawn by hand, borrowed from another glyph, or mirrored from the '
			'other side. Generating writes over all three.\n\n'
			'Keep Them generates only the sides that hold nothing. Sides set to '
			'auto are not counted either way: they ask to be kept up to date.',
			('Keep Them', f'Overwrite {sides.title()}', 'Cancel'))
		return {0: self.KEEP, 1: self.OVERWRITE, 2: self.CANCEL}.get(answer, self.CANCEL)

	@objc.python_method
	def generateBubbles(self, allMasters):
		"""Auto-generate both walls for the selected glyphs."""
		try:
			import PKBubbleStore
			import PKTool
			font = Glyphs.font
			if font is None:
				return
			layers = self.selectedLayers(allMasters)
			if not layers:
				return
			# WHAT IS ALREADY THERE IS SOMEBODY'S WORK, and a run used to write
			# over it without a word - including the references and mirrors,
			# which `writeBubble` clears as it goes. Counted across both sides,
			# because a run does both.
			skipExisting = False
			existing = PKBubbleStore.countExisting(layers)
			if existing:
				answer = self.askAboutExisting(existing)
				if answer == self.CANCEL:
					return
				skipExisting = answer == self.KEEP
			# THE STORE, NOT THE TOOL. Generating a bubble is writing userData
			# on a layer and needs no canvas; going through the live tool meant
			# this command failed outright when the tool had not been picked up
			# yet. Only the redraw wants the tool, and only if there is one.
			for isLeft in (True, False):
				PKBubbleStore.autoGenerate(font, isLeft, layers=layers,
					skipExisting=skipExisting)
			if PKTool.mainDrawingHandler is not None:
				PKTool.mainDrawingHandler.refreshAfterWrite()
		except Exception:
			PKCommonLogic.log(f'generateBubbles error: {traceback.format_exc()}', error=True)

	# THE PANES OF THE ONE WINDOW, and what the toolbar calls them.
	KERNER, GROUPS, EXPORT, SETTINGS = 'kerner', 'groups', 'export', 'settings'
	WINDOW_SIZE = (840, 500)
	settingsTool = None  # a class default; see the note on _relevantRows
	groupGrid = None

	@objc.python_method
	def buildWindow(self):
		self.font = Glyphs.font  # allows the plugin to stick to the initially given font
		# ONE WINDOW FOR ALL OF IT, PICKED FROM THE TOOLBAR. The kerner and the
		# settings were two floating windows over the same canvas, and neither
		# is any use without the other: the settings decide what a wall looks
		# like and the kerner decides what to do with it. The font export was
		# a tab inside the kerner, which made it look like a step of kerning
		# rather than the separate, experimental thing it is.
		#
		# ONE SIZE FOR EVERY PANE, deliberately: the alternative is a window
		# that jumps size every time the toolbar is clicked. The kerner and
		# the settings both fill it; the export pane centres itself in it.
		self.w = vanilla.Window(
			self.WINDOW_SIZE,
			minSize=(700, 420),
			maxSize=(2000, 2000),
			title='PolyKern',
			autosaveName="com.Tosche.PolyKernKerner.mainwindow"  # stores last window position and size
		)

		self.w.bind("should close", self.windowShouldClose_)
		self.w._window.setLevel_(NSFloatingWindowLevel)  # MAKE WINDOW FLOAT
		windowNS = self.w.getNSWindow()
		windowNS.setHidesOnDeactivate_(True)  # MAKE WINDOW HIDE WHILE IN BACKGROUND

		# POSSIZE, NOT RULES, for the panes themselves: they are both the whole
		# window, and a container placed by rules cannot hold one placed by
		# posSize. Each pane lays its own contents out however it likes.
		self.w.kernerPane = vanilla.Group((0, 0, 0, 0))
		self.w.groupsPane = vanilla.Group((0, 0, 0, 0))
		self.w.exportPane = vanilla.Group((0, 0, 0, 0))
		self.w.settingsPane = vanilla.Group((0, 0, 0, 0))

		# NO TAB VIEW ANY MORE. It carried "Generate Kerning" and "Generate
		# Bubbled Fonts", and once the toolbar existed the window had two ways
		# of asking the same question - a tab bar nested inside a pane picker.
		# Each of the two is a pane of its own now, and the tabs are gone.
		self.buildKerningPane()
		self.buildGroupsPane()
		self.buildExportPane()
		self.buildSettingsPane()
		self.addPaneToolbar()
		self.showPane(self.KERNER)

	# BUMP THIS WHENEVER THE ITEMS CHANGE. NSToolbar autosaves which items are
	# in it against this name, and a saved configuration WINS over the ones the
	# delegate offers - so anybody who had opened the two-item version would
	# have gone on seeing two items, and the new panes would simply not be
	# there. A name it has never saved under has nothing to restore.
	TOOLBAR_NAME = 'PolyKernPanes.4'

	# THE ARTWORK THAT SITS AMONG THE SYMBOLS, and how tall its ink has to be
	# to stand level with them. Measured rather than guessed: at the size the
	# toolbar draws them, `gear` carries 13.9 points of ink and
	# `rectangle.stack.fill` 15.
	KERNER_ICON = 'PK_KernerIcon.pdf'
	KERNER_ICON_INK = 14.0

	@objc.python_method
	def kernerIcon(self):
		"""The Kerner's own artwork, sized to stand level with SF Symbols.

		A SYMBOL IS SIZED BY ITS INK AND A PDF BY ITS PAGE. Handed over as it
		is, the mark would be sized by whatever margin the export happened to
		leave round it - 4 points top and bottom, in this one, which is a
		tenth of the page. The ink is measured and scaled instead, so redrawing
		the artwork does not move it.

		-> NSImage, or None to let the caller fall back to a symbol.
		"""
		try:
			path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
				self.KERNER_ICON)
			artwork = NSImage.alloc().initByReferencingFile_(path)
			if artwork is None or not artwork.isValid():
				log(f'kernerIcon: no artwork at {path}', error=True)
				return None
			return PKIcon.trimmedIcon(artwork, self.KERNER_ICON_INK)
		except Exception:
			log(f'kernerIcon error: {traceback.format_exc()}', error=True)
			return None

	@objc.python_method
	def addPaneToolbar(self):
		"""The panes, as the entries of a toolbar.

		LEFT ALIGNED, WITH THE EXPORT HELD OUT TO THE RIGHT. The three that are
		part of kerning something sit together; the experimental font export is
		put where nothing is next to it. `preference` style would centre the
		lot, so the style is `expanded`: same two rows, items along the left.
		"""
		try:
			def symbol(name):
				return NSImage.imageWithSystemSymbolName_accessibilityDescription_(
					name, None)
			items = [
				dict(itemIdentifier=self.KERNER, label='Kerner',
					toolTip='Which pairs to kern, and kerning them',
					# ITS OWN MARK, not a symbol that means something near it.
					imageObject=self.kernerIcon() or symbol('text.justify.left'),
					imageTemplate=True,
					selectable=True, callback=self.pickKerner),
				dict(itemIdentifier=self.GROUPS, label='Groups',
					toolTip='Which glyphs share a wall, and what they share',
					imageObject=symbol('rectangle.stack.fill'), imageTemplate=True,
					selectable=True, callback=self.pickGroups),
				dict(itemIdentifier=self.SETTINGS, label='Settings',
					toolTip='What a wall is shaped like, and what the kerner '
						'does with it',
					imageObject=symbol('gear'), imageTemplate=True,
					selectable=True, callback=self.pickSettings),
				dict(itemIdentifier=NSToolbarFlexibleSpaceItemIdentifier),
				dict(itemIdentifier=self.EXPORT, label='PK Export',
					toolTip='Generate a font with the walls baked into it as '
						'a BBLH table',
					imageObject=symbol('square.and.arrow.up'), imageTemplate=True,
					selectable=True, callback=self.pickExport),
			]
			self.w.addToolbar(self.TOOLBAR_NAME, items, addStandardItems=False,
				displayMode='iconLabel', toolbarStyle='expanded')
			# NOT THE USER'S TO REARRANGE. It picks which pane is showing, and
			# a pane picker missing a pane is a feature that has vanished.
			# With customising off there is nothing to save either.
			toolbar = self.w.getNSWindow().toolbar()
			if toolbar is not None:
				toolbar.setAllowsUserCustomization_(False)
				toolbar.setAutosavesConfiguration_(False)
		except Exception:
			log(f'addPaneToolbar error: {traceback.format_exc()}', error=True)

	# ONE CALLBACK PER PANE, NOT ONE THAT READS THE SENDER. What vanilla hands
	# a toolbar callback is not worth guessing at from two lines away.
	@objc.python_method
	def pickKerner(self, sender=None):
		self.showPane(self.KERNER)

	@objc.python_method
	def pickGroups(self, sender=None):
		self.showPane(self.GROUPS)

	@objc.python_method
	def pickExport(self, sender=None):
		self.showPane(self.EXPORT)

	@objc.python_method
	def pickSettings(self, sender=None):
		self.showPane(self.SETTINGS)

	@objc.python_method
	def paneGroups(self):
		"""-> {identifier: the Group that is that pane}"""
		return {self.KERNER: self.w.kernerPane, self.GROUPS: self.w.groupsPane,
			self.EXPORT: self.w.exportPane, self.SETTINGS: self.w.settingsPane}

	@objc.python_method
	def showPane(self, which):
		"""Show one pane and hide the rest, toolbar in step."""
		try:
			# READ AGAIN ON EVERY VISIT, not once when the window is built. The
			# references this draws are written by the tool, by Set Refer
			# Glyphs Automatically and by hand, all of it while this window is
			# open beside the canvas.
			if which == self.GROUPS:
				self.refreshGroups()
			for identifier, pane in self.paneGroups().items():
				pane.show(identifier == which)
			toolbar = self.w.getNSWindow().toolbar()
			if toolbar is not None:
				toolbar.setSelectedItemIdentifier_(which)
		except Exception:
			log(f'showPane error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def buildGroupsPane(self):
		"""Every glyph that borrows a wall, beside the one it borrows it from.

		A REFERENCE IS THE ONLY PLACE TWO GLYPHS REALLY DO SHARE A FINGERPRINT.
		Two walls that came out the same shape are still two walls, and drift
		apart the moment either glyph is touched; a kerning key is one wall
		read from two places. So this is a picture of the references, not of
		what happens to look alike.

		THE GRID IS THE ONE Set Kerning Keys Automatically SHOWS. It draws each
		glyph with its measured wall on the side it was grouped on, which is
		the whole point: a list of names cannot say whether a grouping is any
		good, and the glyphs side by side say it at a glance.
		"""
		try:
			pane = self.w.groupsPane
			# THE COMMAND THAT MAKES THE GROUPS, WITH THE GROUPS. It was an
			# item in the settings pane's action menu, two panes away from the
			# grid that shows what it did.
			pane.autoButton = vanilla.Button(
				(-self.AUTO_BUTTON_W - 15, 10, self.AUTO_BUTTON_W, 20),
				'Set Kerning Keys Automatically…', sizeStyle='small',
				callback=self.setKerningKeys)
			pane.caption = vanilla.TextBox(
				(15, 12, -self.AUTO_BUTTON_W - 30, 32), '', sizeStyle='small')
			# THE WIDTH IS A PLACEHOLDER. The scroll view sets its document
			# view's width, and the grid lays itself out again when it does.
			grid = PKGroupGridView.alloc().initWithFrame_(NSMakeRect(0, 0, 800, 1))
			grid.setAutoresizingMask_(NSViewWidthSizable)
			self.groupGrid = grid
			pane.groups = vanilla.ScrollView((0, 52, 0, 0), grid,
				hasHorizontalScroller=False)
		except Exception:
			log(f'buildGroupsPane error: {traceback.format_exc()}', error=True)

	# WIDE ENOUGH FOR ITS OWN TITLE. A vanilla Button truncates rather than
	# growing, and a truncated command is one nobody presses.
	AUTO_BUTTON_W = 215

	@objc.python_method
	def setKerningKeys(self, sender=None):
		"""Hand the run to the tool, which owns it and the sheet it asks with.

		THE TOOL, NOT THIS PLUGIN. Measuring a wall is the tool's work and the
		settings that decide the shape are the tool's too; all this does is
		ask, from the pane where the answer will show up.
		"""
		try:
			import PKTool
			tool = PKTool.mainDrawingHandler
			if tool is None:
				# THE TOOL IS A SEPARATE PRINCIPAL CLASS of this bundle and may
				# not have been made yet.
				PKCommonLogic.show_alert('Set Kerning Keys Automatically',
					'The PolyKern tool has not loaded yet. Pick it in the '
					'toolbar once, then try again.', cancel=False)
				return
			tool.openAutoGroupWindow()
		except Exception:
			log(f'setKerningKeys error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def groupsCaption(self, groups) -> str:
		"""What the grid below adds up to, in words. -> str"""
		if not groups:
			return ('No glyph borrows a wall from another one in this master. '
				'Put a glyph name in a side\u2019s Kerning Key field, or run Set '
				'Kerning Keys Automatically, and the groups appear here.')
		# ACROSS BOTH SIDES: a glyph can be in a left group and a right one,
		# and it is still one glyph.
		glyphs = len({name for group in groups for name in group['members']})
		return (f'{len(groups)} group{"" if len(groups) == 1 else "s"}, '
			f'{glyphs} glyph{"" if glyphs == 1 else "s"}. Each band is one wall '
			'shared by everything in it, and the first cell is the glyph the '
			'rest of them borrow it from.')

	@objc.python_method
	def fitGroupGrid(self):
		"""Make the grid as wide as the scroll view showing it. -> None

		A SCROLL VIEW DOES NOT SIZE ITS DOCUMENT VIEW - it scrolls whatever it
		is given, at whatever size that is. The autoresizing mask keeps the two
		in step as the window is dragged, but a mask only ever acts on a LATER
		resize: the grid is made at a placeholder width, and without this it
		would sit at that width with a strip of nothing beside it until
		somebody happened to resize the window. Same trap as the preview view.
		"""
		try:
			grid = self.groupGrid
			if grid is None:
				return
			width = float(self.w.groupsPane.groups.getNSScrollView()
					.contentView().bounds().size.width)
			if width > 1:
				grid.relayout(width)
		except Exception:
			log(f'fitGroupGrid error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def refreshGroups(self):
		"""Read the font's references again and redraw the grid."""
		try:
			grid = self.groupGrid
			if grid is None:
				return
			self.fitGroupGrid()
			font = Glyphs.font or self.font
			master = font.selectedFontMaster if font is not None else None
			if font is None or master is None:
				grid.setGroups([], font, None)
				self.w.groupsPane.caption.set('Open a font to see its groups.')
			else:
				groups = store.referGroups(font, master.id)
				grid.setGroups(groups, font, master.id)
				self.w.groupsPane.caption.set(self.groupsCaption(groups))
			grid.setNeedsDisplay_(True)
		except Exception:
			log(f'refreshGroups error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def buildSettingsPane(self):
		"""The tool's settings, built into this window's second pane.

		THE TOOL OWNS THESE CONTROLS, not this plugin - they drive the canvas,
		and every one of their callbacks is a method of the tool. All this does
		is hand the tool somewhere to put them. Its methods reach their
		controls through `setW`, and a Group answers to that exactly as the
		floating window it used to make did.

		-> True when the pane was filled.
		"""
		try:
			import PKTool
			pane = self.w.settingsPane
			tool = PKTool.mainDrawingHandler
			if tool is None:
				# THE TOOL IS A SEPARATE PRINCIPAL CLASS of this bundle and may
				# not have been instantiated yet. Say so in the pane rather
				# than leaving it blank.
				pane.notLoaded = vanilla.TextBox((20, 20, -20, 60),
					'The PolyKern tool has not loaded yet, so its settings are '
					'not here. Pick the PolyKern tool in the toolbar once, then '
					'reopen this window.')
				return False
			tool.setW = pane
			# THE TOOL PLACES ITS OWN CONTROLS. This used to pass three
			# magic numbers across the bundle, which then had to be kept in
			# step with the standalone window's copy of them.
			tool.buildSettings(pane)
			tool.loadSettings()  # ONE PATH INTO THE CONTROLS, opening included
			Glyphs.addCallback(tool.settingsInterfaceUpdate, UPDATEINTERFACE)
			self.settingsTool = tool
			return True
		except Exception:
			log(f'buildSettingsPane error: {traceback.format_exc()}', error=True)
			return False

	@objc.python_method
	def buildKerningPane(self):
		"""The presets table and what a run does with it."""
		pane = self.w.kernerPane  # STANDARD KERNING GENERATION
		pane.group0 = vanilla.Group('auto')  # TABLES TO MAKE AUTO LAYOUT EASIER
		pane.group1 = vanilla.Group('auto')  # BUTTONS

		pane.group0.optionsPopup = vanilla.PopUpButton('auto', popupOptions, callback=self.popupTasks)  # POPUP MENU
		pane.group0.optionsPopup._nsObject.menu().setAutoenablesItems_(False) # what does it do?

		emptyPermutation = [{"Kern": True, "Left": "A B C", "Right": "X Y Z", "Add Flipped": True, "Pairs": "0"}]  # TITLE

		dragSettings = dict(
			makeDragDataCallback=self.makeDragDataCallback
		)
		dropSettings = dict(
			pasteboardTypes=[
				"string",
				"Tosche.PolyKernKerner.permListIndexes"
			],
			dropCandidateEnteredCallback=self.dropCandidateEnteredCallback,
			dropCandidateCallback=self.dropCandidateCallback,
			performDropCallback=self.performDropCallback
		)

		pane.group0.permList = vanilla.List2(
			'auto',
			items=emptyPermutation,
			columnDescriptions=[
				# WHICH ROWS A RUN USES. Off is not deleted: a row is somebody's
				# thinking about what needs kerning, and turning it off for one
				# run should not cost them it.
				{"title": "Kern",
					"identifier": "Kern",
					"cellClass": vanilla.CheckBoxList2Cell,
					"editable": True,
					"width": 40},
				{"title": "Left", "identifier": "Left"},
				{"title": "Right", "identifier": "Right"},
				{"title": "Add Flipped",
					"identifier": "Add Flipped",
					"cellClass": vanilla.CheckBoxList2Cell,
					"editable": True,
					"width": 70},
				{"title": "Pairs", "identifier": "Pairs", "width": 60},
			],
			dragSettings=dragSettings,
			dropSettings=dropSettings,
			autohidesScrollers=True,
			allowsEmptySelection=False,
			allowsMultipleSelection=False,
			selectionCallback=self.permListSelected,
			editCallback=self.checkBoxClicked,
			doubleClickCallback=self.permListDoubleClick,
		)

		tableView = pane.group0.permList._tableView
		tableView.setAllowsColumnReordering_(False)
		tableView.unbind_("sortDescriptors")  # Disables sorting by clicking the title bar
		# INDEXED, SO THE Kern COLUMN SHIFTED THEM ALL ALONG ONE. Only Left and
		# Right stretch; the three narrow ones stay the width they were given.
		tableView.tableColumns()[0].setResizingMask_(0)  # Kern
		tableView.tableColumns()[1].setResizingMask_(1)  # Left
		tableView.tableColumns()[2].setResizingMask_(1)  # Right
		tableView.tableColumns()[3].setResizingMask_(0)  # Add Flipped
		tableView.tableColumns()[4].setResizingMask_(0)  # Pairs
		tableView.setColumnAutoresizingStyle_(1)
		# setResizingMask_() 0=Fixed, 1=Auto-Resizable (Not user-resizable). There may be more options?
		# setColumnAutoresizingStyle accepts value from 0 to 5.
		# For detail,see: http://api.monobjc.net/html/T_Monobjc_AppKit_NSTableViewColumnAutoresizingStyle.htm


		pane.group0.preview = vanilla.TextEditor('auto', "", readOnly=True)
		pane.group0.preview._textView.setFont_(Menlo12)
		# ADD & DELETE BUTTONS:
		plusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
		pane.group0.addButton = vanilla.ImageButton('auto', imageObject=plusImage, callback=self.addButton)
		minusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("trash", None)
		pane.group0.delButton = vanilla.ImageButton('auto', imageObject=minusImage, callback=self.delButton)

		# THE ADD AND DELETE BUTTONS ARE NOT IN HERE. They are pinned to the
		# list's own bottom right corner below, which the visual format
		# language cannot say: it can put a view after another one, not on it.
		rules = [
			'H:|-[optionsPopup]',
			'H:|-[permList(>=600)][preview(200)]-|',
			'V:|[optionsPopup]-[permList(>=100)]-|',
			'V:[optionsPopup]-[preview]-|',
		]
		metrics = {}
		pane.group0.addAutoPosSizeRules(rules, metrics)
		self.pinListButtons(pane.group0)

		pane.group1.progress = vanilla.ProgressBar('auto', maxValue=100)
		pane.group1.progress.show(False)
		# THE PAIRS THAT ACTUALLY OCCUR, ON TOP OF THE PRESET'S. The rows say
		# which glyphs are in scope and pair them exhaustively; this list says
		# which combinations turn up in text, whatever the rows happen to
		# cover. Added to them, not imposed on them - a row asking for
		# something the list has never heard of is still a row somebody wrote.
		pane.group1.includeRelevant = vanilla.CheckBox('auto', 'Include the most relevant pairs',
			value=bool(PKAutoBubble._pref(PKAutoBubble.PREF_INCLUDE_RELEVANT, False)),
			callback=self.toggleIncludeRelevant, sizeStyle='small')
		pane.group1.includeRelevant.getNSButton().setToolTip_(
			'Also kern the pairs that occur in running text, after André '
			'Fuchs\u2019s kerning-pairs, whether or not the list above asks '
			'for them')
		# ONE BUTTON. What a run covers is decided in the list now - the Kern
		# column - rather than by which of two buttons was pressed.
		# WHAT THE LIST IS, FOR ANYONE WHO HAS NOT MET IT. A tooltip can say a
		# sentence; this one needs a paragraph and the 3,736 pairs themselves.
		infoImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
			"info.circle", None)
		pane.group1.infoButton = vanilla.ImageButton('auto', imageObject=infoImage,
			bordered=False, callback=self.showRelevantPairs)
		pane.group1.infoButton.getNSButton().setToolTip_(
			'What the most relevant pairs are, and which ones they are')

		pane.group1.applyButton = vanilla.Button('auto', "Apply Kerning",
			sizeStyle="regular", callback=self.PolyKernMain)
		# DIRECTLY OVER THE BUTTON IT DESCRIBES. It used to sit under the list,
		# a column away from the button that acts on it.
		pane.group1.total = vanilla.TextBox('auto', totalPairsPrefix,
			alignment="right", sizeStyle="small")
		# ONE CHAIN TOP TO BOTTOM, AND ONE ONLY. The bar has no height of its
		# own beyond what its rules give it, so something must reach the bottom
		# or it collapses to nothing; but two chains pinned at both ends have
		# to agree on the height to the point, and when they cannot auto layout
		# breaks one and drops the view where it likes. The total and the
		# button it counts for are that chain. Everything else hangs from the
		# top and stops.
		rules = [
			'H:|-[includeRelevant]-[infoButton(18)]-[progress]-[applyButton]-|',
			'H:[total]-|',
			'V:|-(6)-[total(14)]-(4)-[applyButton(30)]-(8)-|',
			'V:|-(30)-[includeRelevant(18)]',
			'V:|-(30)-[infoButton(18)]',
			'V:|-(28)-[progress]',
		]
		pane.group1.addAutoPosSizeRules(rules, metrics)

		# THE TOP MARGIN HAS TO BE ASKED FOR NOW. The tab view inset whatever
		# it held; a pane sitting straight in the window insets nothing.
		rules = [
			'H:|[group0(>=100)]|',
			'H:|[group1(>=100)]|',
			'V:|-(8)-[group0][group1]|',
		]
		pane.addAutoPosSizeRules(rules, None)

	# SMALL ENOUGH TO SIT ON THE LIST WITHOUT COVERING A ROW.
	LIST_BUTTON_W, LIST_BUTTON_H = 26.0, 20.0
	LIST_BUTTON_INSET, LIST_BUTTON_GAP = 12.0, 3.0

	@objc.python_method
	def pinListButtons(self, group):
		"""Sit the add and delete buttons on the list's bottom right corner.

		AFTER `addAutoPosSizeRules`, and left out of its rules: vanilla places
		what its rules name and would otherwise put these two in a row under
		the list. Drawing over it is a matter of subview order, and both were
		made after the list, so they are already on top.
		"""
		try:
			listView = group.permList.getNSScrollView()
			add = group.addButton.getNSButton()
			delete = group.delButton.getNSButton()
			pinned = []
			for button in (add, delete):
				button.setTranslatesAutoresizingMaskIntoConstraints_(False)
				pinned += [
					button.widthAnchor().constraintEqualToConstant_(self.LIST_BUTTON_W),
					button.heightAnchor().constraintEqualToConstant_(self.LIST_BUTTON_H),
					button.bottomAnchor().constraintEqualToAnchor_constant_(
						listView.bottomAnchor(), -self.LIST_BUTTON_INSET),
				]
			pinned += [
				delete.trailingAnchor().constraintEqualToAnchor_constant_(
					listView.trailingAnchor(), -self.LIST_BUTTON_INSET),
				add.trailingAnchor().constraintEqualToAnchor_constant_(
					delete.leadingAnchor(), -self.LIST_BUTTON_GAP),
			]
			NSLayoutConstraint.activateConstraints_(pinned)
		except Exception:
			log(f'pinListButtons error: {traceback.format_exc()}', error=True)

	# WIDE ENOUGH FOR THE LONGEST LINE THE CAPTION HAS. Under it the paragraph
	# wraps, and it is written in lines that are meant to stay lines.
	CAPTION_WIDTH = 600

	@objc.python_method
	def buildExportPane(self):
		"""Exporting a font with the bubbles baked in as BBLH."""
		pane = self.w.exportPane
		pane.caption = vanilla.TextBox('auto', """This feature is EXPERIMENTAL and may not work as expected.

1. You can generate a new font with 'BBLH' table based on the PolyKern data.
(Maybe also vertical 'BBLV' table in the future)

2. You need to have FontTools installed.
Install it in Glyphs Python using this Terminal command: "pip install fonttools"

3. Interpolation is currently not supported. Only the instances matching masters will be exported.

4. The font format is set in the "Export..." menu.""")
		pane.exportButton = vanilla.Button('auto', 'Generate Bubbled Font', self.generateBubbledFont)
		pane.getHTMLButton = vanilla.Button('auto', 'Get HTML tester', self.getHTMLforBBLH)
		pane.getHTMLButton.enable(False)
		pane.spacer0 = vanilla.Group('auto')
		pane.spacer1 = vanilla.Group('auto')
		pane.spacer2 = vanilla.Group('auto')
		pane.spacer3 = vanilla.Group('auto')
		# THE BUTTONS GET THEIR OWN PAIR. Sharing the caption's meant pinning
		# their width pinned the caption's too, and the paragraph came out a
		# 200 point column.
		pane.spacer4 = vanilla.Group('auto')
		pane.spacer5 = vanilla.Group('auto')
		# EVERY WIDTH IS STATED, because between two spacers that are only said
		# to equal each other nothing here has a width auto layout has to
		# respect - it has a free choice, and takes it differently from run to
		# run: these rules put the button at 214 points in one process and at
		# 587, the whole window, in the next. CAPTION_WIDTH clears the longest
		# line in the paragraph, which is what stops it wrapping.
		rules = [
			'H:|[spacer0(==spacer1)]-[caption(%d)]-[spacer1]|' % self.CAPTION_WIDTH,
			'H:|[spacer4(==spacer5)]-[exportButton(200)]-[spacer5]|',
			'H:|[spacer4]-[getHTMLButton(200)]-[spacer5]|',
			'V:|[spacer2(==spacer3)]-[caption]-(20)-[exportButton]-[getHTMLButton]-[spacer3]|',
		]
		pane.addAutoPosSizeRules(rules, None)
		self.pinExportRibbon(pane)

	# THE CORNER IT SITS IN, in points from the pane's top right.
	RIBBON_INSET = 0.0
	exportRibbon = None

	@objc.python_method
	def pinExportRibbon(self, pane):
		"""Sit a BETA ribbon in the export pane's top right corner.

		OUTSIDE THE RULES, like the list's add and delete buttons: the visual
		format language can put a view after another one, not over the corner
		of the pane itself. Added last, so it is the last subview and draws on
		top of everything the rules placed.
		"""
		try:
			size = PKRibbon.RIBBON_SIZE
			ribbon = PKRibbon.PKRibbonView.alloc().initWithFrame_(
				NSMakeRect(0, 0, size, size))
			ribbon.setWord('BETA')
			self.exportRibbon = ribbon
			view = pane.getNSView()
			view.addSubview_(ribbon)
			ribbon.setTranslatesAutoresizingMaskIntoConstraints_(False)
			NSLayoutConstraint.activateConstraints_([
				ribbon.widthAnchor().constraintEqualToConstant_(size),
				ribbon.heightAnchor().constraintEqualToConstant_(size),
				ribbon.topAnchor().constraintEqualToAnchor_constant_(
					view.topAnchor(), self.RIBBON_INSET),
				ribbon.trailingAnchor().constraintEqualToAnchor_constant_(
					view.trailingAnchor(), -self.RIBBON_INSET),
			])
		except Exception:
			log(f'pinExportRibbon error: {traceback.format_exc()}', error=True)

	def showWindow_(self, sender):
		try:
			self.font = Glyphs.font
			if self.font is None:  # no open font
				return
			if self.w is None:  # no open window yet
				self.buildWindow()
				self.loadedPresetName = None

			self.loadPreferences()  # load permList
			self.refreshTotal() # update total pairs count
			self.w.open()
		except Exception:
			log(f'showWindow_ error: {traceback.format_exc()}', error=True)

	def windowShouldClose_(self, sender):  # User attempts to close the main window
		# THE SETTINGS ARE IN THIS WINDOW NOW, and what the sliders say has to
		# reach the font before it goes away. The window only hides, so the
		# tool's own close handler never runs.
		if self.settingsTool is not None:
			try:
				self.settingsTool.applySettings()
			except Exception:
				log(f'applySettings on close: {traceback.format_exc()}', error=True)
		if self.w:
			self.w.hide()  # hide the window instead of closing
		return False   # IMPORTANT: prevents actual close


	@objc.python_method
	def popupTasks(self, sender):  # dealing with presets popup
		try:
			index = sender.get()
			presetsDicLength = len(self.presetsDic) + 1

			# preset menu items
			if index == presetsDicLength + 0: # new name
				newName = PKCommonLogic.show_alert('Enter Name for new Preset.', askString=True)
				if not newName:
					return
				if newName in self.presetsDic.keys():
					PKCommonLogic.show_alert('Duplicate name is not allowed.', cancel=False)
					return
				# empty names are already handled in show_alert
				self.loadedPresetName = newName
				self.savePreferences(option=2) # 2 = new
				self.refreshPopupButton()
				self.loadPreferences()

			elif index == presetsDicLength + 1: # rename
				newName = PKCommonLogic.show_alert(f'Enter New Name for the Preset: {self.loadedPresetName}', askString=True)
				if not newName:
					return
				self.presetsDic[newName] = self.presetsDic.pop(self.loadedPresetName) # remove and return the same dic entry
				self.loadedPresetName = newName
				self.savePreferences()
				self.refreshPopupButton()
			
			elif index == presetsDicLength + 2: # duplicate
				newName = PKCommonLogic.show_alert(f'Enter Name for the Duplicate of Preset: {self.loadedPresetName}', askString=True)
				if not newName:
					return
				if newName in self.presetsDic.keys():
					PKCommonLogic.show_alert('Existing preset name is not allowed.', cancel=False)
					return
				self.presetsDic[newName] = self.presetsDic[self.loadedPresetName] # just copy the same dic entry
				self.loadedPresetName = newName
				self.savePreferences()
				self.refreshPopupButton()
				self.loadPreferences()

			elif index == presetsDicLength + 3: # delete
				if len(self.presetsDic) <= 1: # only one or zero preset to delete
					PKCommonLogic.show_alert("You can't delete the last preset.", cancel=False)
					self.w.kernerPane.group0.optionsPopup.set(0)
				else:
					deleting = PKCommonLogic.show_alert(f'Are you sure you want to delete "{self.loadedPresetName}"?')
					if deleting:
						self.savePreferences(option=1) # deleting

			else: # presets selected
				self.loadedPresetName = sender.getItem()
				self.loadPreferences()
		except Exception:
			log(f'popupTasks error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def refreshPopupButton(self):  # refresh option popup items
		try:
			presetsDicNames = sorted([k for k in self.presetsDic.keys()])
			thePopup = self.w.kernerPane.group0.optionsPopup

			thePopup.setItems(presetsDicNames + popupOptions)

			# add separator
			menu = thePopup._nsObject.menu()
			divider0 = NSMenuItem.separatorItem()
			menu.insertItem_atIndex_(divider0, len(self.presetsDic))
			menu.itemAtIndex_(len(self.presetsDic)).setEnabled_(False)  # disable separator

			# set selection to the loaded preset
			thePopup.set(presetsDicNames.index(self.loadedPresetName))

		except Exception:
			log(f'refreshPopupButton error: {traceback.format_exc()}', error=True)
			

	@objc.python_method
	def loadPreferences(self, sender=None):
		try:
			try:
				presetsDic = Glyphs.defaults["com.Tosche.PolyKern.presetsDic"]
			except Exception: # if old PolyKern is being used
				presetsDic = Glyphs.defaults["com.Tosche.PolyKern.favDic"]
				del Glyphs.defaults["com.Tosche.PolyKern.favDic"]
				Glyphs.defaults["com.Tosche.PolyKern.presetsDic"] = presetsDic

			# I need NSMutableDictionary to modify dictionary; without it, I cannot change teh content
			self.presetsDic = NSMutableDictionary.alloc().initWithDictionary_copyItems_(presetsDic, True)

			if Glyphs.defaults["com.Tosche.PolyKern.presetsDic"] is None:
				# Fallback to default preset dictionary
				self.presetsDic = {
					"Sample": (
						(
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z",  # Left
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z",  # Right
							False,  # add flipped
						),
						(
							"a b c d e f g h i j k l m n o p q r s t u v w x y z",
							"a b c d e f g h i j k l m n o p q r s t u v w x y z",
							False,
						),
						(
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z",
							"a b c d e f g h i j k l m n o p q r s t u v w x y z",
							False,
						),
						(
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z a b c d e f g h i j k l m n o p q r s t u v w x y z",
							"period comma exclam question quoteleft quoteright",
							True,
						),
					)
				}

				Glyphs.defaults["com.Tosche.PolyKern.presetsDic"] = self.presetsDic
			else:  # presetsDic exists, but not validated
				pass

			# which dic to set
			if sender == self.w.kernerPane.group0.optionsPopup:
				log('Popup is loading')
			elif sender == self.w.kernerPane.group0.permList:  # the permList has been edited
				log('List view is loading')
			else: # on first load; load the first item?
				if not self.loadedPresetName:
					self.loadedPresetName = sorted([k for k in self.presetsDic.keys()])[0] # name of the preset
				preset = self.presetsDic[self.loadedPresetName]
				permutations = []
				for perm in preset:
					dictToSet = {}
					dictToSet['Left'] = perm[0]
					dictToSet['Right'] = perm[1]
					dictToSet['Add Flipped'] = perm[2]
					# THE FOURTH IS NEW. Presets saved before the Kern column
					# existed are three long, and every row in them was on.
					dictToSet['Kern'] = bool(perm[3]) if len(perm) > 3 else True
					pairsCount = self.pairsCount(perm[0], perm[1], perm[2])
					dictToSet['Pairs'] = pairsCount
					permutations.append(dictToSet)
				self.w.kernerPane.group0.permList.set(permutations)

				self.refreshPopupButton()  # load popup

		except Exception:
			log(f'loadPreferences error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def savePreferences(self, option=0): # 0=save, 1=delete, 2=new
		# rewrite as if it's called every time permList is dragged, or list content edited
		try:
			if option == 1: # deleting the selected preset
				del self.presetsDic[self.loadedPresetName]
				self.loadedPresetName = None
				Glyphs.defaults["com.Tosche.PolyKern.presetsDic"] = self.presetsDic
				# need to load something
				self.loadPreferences()
			elif option == 2: # making new list
				self.presetsDic[self.loadedPresetName] = [('A B C', 'X Y Z', True, True)]
			else: # saving
				permList = self.w.kernerPane.group0.permList.get()
				perms = []
				for item in permList: # for each line
					perm = []
					perm.append(item['Left'])
					perm.append(item['Right'])
					perm.append(item['Add Flipped'])
					perm.append(item.get('Kern', True))
					perms.append(perm)
				self.presetsDic[self.loadedPresetName] = perms

			Glyphs.defaults["com.Tosche.PolyKern.presetsDic"] = self.presetsDic
		except Exception:
			log(f'SavePreferences error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def pairsCount(self, text0: str, text1: str, flipped: bool) -> int:
		multiply = 2 if flipped else 1
		return len(self.cleanUpText(text0)) * len(self.cleanUpText(text1)) * multiply

	@objc.python_method
	def refreshPreview(self): # preview EditText
		try:
			permList = self.w.kernerPane.group0.permList
			index = permList.getSelectedIndexes()[0]
			lefts = permList.get()[index]['Left'].split(' ')
			rights = permList.get()[index]['Right'].split(' ')
			count = 200
			lines = ''
			for l in lefts:
				for r in rights:
					lines += f'{l} {r}\n'
					count -= 1
					if count <= 0:
						break
				if count <= 0:
					break
			if permList.get()[index]['Add Flipped']:
				for r in rights:
					for l in lefts:
						lines += f'{r} {l}\n'
						count -= 1
						if count <= 0:
							break
					if count <= 0:
						break
			if count <= 0:
				lines += '(...)'
			self.w.kernerPane.group0.preview.set(lines)
		except Exception:
			log(f'refreshPreview error: {traceback.format_exc()}', error=True)

	RELEVANT_BLURB = (
		"The pairs that actually turn up in running text, from André Fuchs\u2019s "
		"kerning-pairs list \u2014 {count:,} of them, best first.\n\n"
		"A row in the list above pairs every glyph on the left with every glyph "
		"on the right, so it asks for combinations no language ever sets. This "
		"list is the other way round: it names the combinations that do occur, "
		"whatever the rows happen to cover. Ticking the box ADDS them to what "
		"the rows ask for \u2014 it does not narrow the rows.")

	# CLASS DEFAULTS, so an attribute lookup finds these rather than inventing
	# something. The plugin's base class answers to names it has never heard of.
	_relevantRows = None
	relevantPopover = None

	@objc.python_method
	def relevantRows(self):
		"""The whole list, ready for a table. -> [dict]

		Built once. A space is a pair half like any other - 126 of them start
		with one - and an empty cell would read as a missing pair, so it is
		spelled out.
		"""
		if self._relevantRows is None:
			def show(character):
				return {' ': 'space', '\u00a0': 'nbspace'}.get(character, character)
			self._relevantRows = [
				{'#': index, 'Left': show(pair[0]), 'Right': show(pair[1]),
					'Pair': pair}
				for index, pair in enumerate(PKAutoBubble.relevant_pairs(), 1)]
		return self._relevantRows

	POPOVER_SIZE = (380.0, 460.0)
	POPOVER_MARGIN = 16.0

	@objc.python_method
	def paragraphHeight(self, text, width):
		"""How tall `text` needs to be at `width`. -> float

		MEASURED, NOT GUESSED. The first cut of the popover gave the paragraph
		a round 106 points; it wanted 126 and the last two lines were simply
		cut off, with nothing to say so.
		"""
		try:
			font = NSFont.systemFontOfSize_(NSFont.smallSystemFontSize())
			written = NSAttributedString.alloc().initWithString_attributes_(
				text, {NSFontAttributeName: font})
			box = written.boundingRectWithSize_options_(
				NSMakeSize(width, 10000.0), NSStringDrawingUsesLineFragmentOrigin)
			return float(int(box.size.height)) + 4.0  # rounding, and a hair
		except Exception:
			log(f'paragraphHeight error: {traceback.format_exc()}', error=True)
			return 160.0  # too much room reads better than a cut sentence

	@objc.python_method
	def showRelevantPairs(self, sender):
		"""A popover explaining the list, with the list in it."""
		try:
			rows = self.relevantRows()
			wide, high = self.POPOVER_SIZE
			margin = self.POPOVER_MARGIN
			blurb = self.RELEVANT_BLURB.format(count=len(rows))
			said = self.paragraphHeight(blurb, wide - margin * 2)
			popover = vanilla.Popover((wide, high))
			popover.blurb = vanilla.TextBox((margin, 14, -margin, said),
				blurb, sizeStyle='small')
			popover.pairs = vanilla.List2((margin, 14 + said + 12, -margin, -margin), rows,
				columnDescriptions=[
					{"title": "#", "identifier": "#", "width": 50},
					{"title": "Left", "identifier": "Left", "width": 60},
					{"title": "Right", "identifier": "Right", "width": 60},
				],
				allowsEmptySelection=True, autohidesScrollers=True)
			popover.open(parentView=sender, preferredEdge='top')
			self.relevantPopover = popover  # or it is collected while open
		except Exception:
			log(f'showRelevantPairs error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def toggleIncludeRelevant(self, sender=None):
		try:
			Glyphs.defaults[PKAutoBubble.PREF_INCLUDE_RELEVANT] = bool(sender.get())
			self.refreshTotal()
		except Exception:
			log(f'toggleIncludeRelevant error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def presetPairs(self, permutations) -> set:
		"""Every pair these rows ask for, deduped. -> {(str, str)}

		THE WAY A RUN BUILDS THEM, not the sum of the Pairs column: that is a
		product per row, and a pair two rows both name is still one pair.
		"""
		pairs = set()
		for row in permutations:
			if not row.get('Kern', True):
				continue  # switched off in the Kern column
			lefts = self.cleanUpText(row['Left']) or []
			rights = self.cleanUpText(row['Right']) or []
			pairs.update((left, right) for left in lefts for right in rights)
			if row['Add Flipped']:
				pairs.update((right, left) for left in lefts for right in rights)
		return pairs

	@objc.python_method
	def totalCount(self, permutations) -> int:
		"""How many pairs a run would set, the relevant list included. -> int

		ONE ARITHMETIC FOR BOTH ANSWERS. The two used to be counted differently
		- a sum of the row products with the box clear, a deduped set with it
		ticked - so ticking a box that only ever ADDS pairs could make the
		total fall.
		"""
		try:
			pairs = self.presetPairs(permutations)
			if bool(PKAutoBubble._pref(PKAutoBubble.PREF_INCLUDE_RELEVANT, False)):
				font = self.font
				if font is not None:
					pairs |= PKAutoBubble.relevant_pair_names(
						PKCommonLogic.namesByCharacter(font))
			return len(pairs)
		except Exception:
			log(f'totalCount error: {traceback.format_exc()}', error=True)
			return 0

	@objc.python_method
	def refreshTotal(self): # preview EditText
		try:
			permutations = self.w.kernerPane.group0.permList.get()
			totalPairs = self.totalCount(permutations)
			self.w.kernerPane.group1.total.set(totalPairsPrefix + format(totalPairs, ','))
		except Exception:
			log(f'refreshTotal error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def cleanUpText(self, text) -> list:  # Function to clean up the glyph name list in Sheet
		try:
			text = re.sub("[/,\n\t]", " ", text)
			text = text.split()  # turn to a list
			return text
		except Exception:  # The text wasn't ascii-decodable. Probably not a string of glyph names.
			log(f'cleanUpText error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def permListSelected(self, sender):  # when permutation list line has been selected
		groupView = self.w.kernerPane.group0.getNSView()
		if len(groupView.subviews()) <= 1:
			# I want to avoid sender being not ready on the first run
			# 1 means only Popup has been loaded, and the list is not ready yet
			return
		self.refreshPreview()

	@objc.python_method
	def checkBoxClicked(self, sender): # when checkBox is clicked, update Pairs count & save.
		try:
			permutations = sender.get()
			selectedIndexes = sender.getSelectedIndexes()
			editedIndex = sender.getEditedIndex()
			editedRow = permutations[editedIndex]
			pairsCount = self.pairsCount(editedRow['Left'], editedRow['Right'], editedRow['Add Flipped'])
			permutations[editedIndex]['Pairs'] = pairsCount
			sender.set(permutations)

			# need to re-select the same row
			sender.setSelectedIndexes(selectedIndexes)

			# refresh preview text
			self.refreshPreview()

			self.savePreferences()

			# updating the total number of pairs
			self.refreshTotal()
		except Exception:  # The text wasn't ascii-decodable. Probably not a string of glyph names.
			log(f'checkBoxClicked error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def permListDoubleClick(self, sender):  # when permutation list line has been double-clicked, open sheet
		try:
			index = sender.getSelectedIndexes()[0]

			groupText0 = sender.get()[index]["Left"]
			groupText1 = sender.get()[index]["Right"]
			self.s = escapableSheet((600, 600), self.w)
			self.s.label0 = vanilla.TextBox('auto', "Left of pair", sizeStyle="small")
			self.s.label1 = vanilla.TextBox('auto', "Right or pair", sizeStyle="small")
			self.s.edit0 = vanilla.TextEditor('auto', groupText0)
			self.s.edit0._textView.setFont_(Menlo12)
			self.s.edit1 = vanilla.TextEditor('auto', groupText1)
			self.s.edit1._textView.setFont_(Menlo12)
			self.s.instruction = vanilla.TextBox('auto', "Enter list of glyph names; they can be separated by space, slash, comma, tab, or line break.")
			self.s.cancel = vanilla.Button('auto', "Cancel", callback=self.cancelEditPermutation)
			self.s.ok = vanilla.Button('auto', "OK", callback=self.confirmEditPermutation)
			self.s.spacer0 = vanilla.Group('auto')
			self.s.setDefaultButton(self.s.ok)
			rules = [
				'H:|-[label0(==label1)]-[label1]-|',
				'H:|-[edit0(==edit1)]-[edit1]-|',
				'H:|-[instruction]-|',
				'H:|-[spacer0]-[cancel(120)]-[ok(120)]-|',
				'V:|-[label0]-[edit0]-[instruction]-[spacer0]-|',
				'V:|-[label1]-[edit1]-[instruction]-[spacer0]-|',
				'V:|-[label1]-[edit1]-[instruction]-[cancel]-|',
				'V:|-[label1]-[edit1]-[instruction]-[ok]-|',
			]
			self.s.addAutoPosSizeRules(rules)
			self.s.open()
		except Exception:
			log(f'permListDoubleClick error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def cancelEditPermutation(self, sender):  # Close sheet by clicking cancel (esc is implemented as subclass)
		try:
			self.s.close()
		except Exception:
			log(f'cancelEditPermutation error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def confirmEditPermutation(self, sender):
		try:
			# update items

			text1 = self.s.edit0.get()
			text2 = self.s.edit1.get()
			newText1 = ' '.join(self.cleanUpText(text1))
			newText2 = ' '.join(self.cleanUpText(text2))
			if not newText1 or not newText2:
				pass
			else:
				permListUI = self.w.kernerPane.group0.permList
				i = permListUI.getSelectedIndexes()[0]
				content = permListUI.get()
				content[i]["Left"] = newText1
				content[i]["Right"] = newText2
				permListUI.set(content)
				self.s.close()

				self.savePreferences()

				# need to refresh section preview
				self.refreshPreview()
		except Exception:
			log(f'confirmEditPermutation error: {traceback.format_exc()}', error=True)

# DRAG & DROP
	# Establish drag data.
	@objc.python_method
	def makeDragDataCallback(self, index):
		try:
			permList = self.w.kernerPane.group0.permList

			indexes = [index]

			typesAndValues = {
				"str": permList.get()[index],
				"Tosche.PolyKernKerner.permListIndexes": indexes
			}
			return typesAndValues
		except Exception:
			log(f'makeDragDataCallback error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def dropCandidateEnteredCallback(self, info):
		return "generic"

	@objc.python_method
	def dropCandidateCallback(self, info):
		source = info["source"]
		if source == self.w.kernerPane.group0.permList:
			return "move"
		return "copy"

	@objc.python_method
	def performDropCallback(self, info):
		try:
			sender = info["sender"]
			source = info["source"]
			endIndex = info["index"] # proposed drop index
			items = info["items"]

			permList = self.w.kernerPane.group0.permList

			# reorder
			if source == permList:
				# indexes = original indexes of items being carried.
				indexes = sender.getDropItemValues(items, "Tosche.PolyKernKerner.permListIndexes")[0]
				if endIndex > indexes[0]:
					endIndex -= 1
				listItems = list(permList.get())

				movingChunk = [listItems.pop(i) for i in reversed(indexes)][::-1]
				listItems[endIndex:endIndex] = movingChunk
				permList.set(listItems)

				self.savePreferences()

				# Do the same in userData too
			return True
		except Exception:
			log(f'performDropCallback error: {traceback.format_exc()}', error=True)
# / DRAG & DROP

	@objc.python_method
	def addButton(self, sender):  # add a permutation
		try:
			permList = self.w.kernerPane.group0.permList
			listToSet = permList.get()
			listToSet += [{'Kern': True, 'Left': 'A B C', 'Right': 'X Y Z', 'Add Flipped': True, "Pairs": "0"}]
			permList.set(listToSet)

			# enable delButton if there's multiple: maybe move elsewhere
			if len(listToSet) > 1:
				self.w.kernerPane.group0.delButton.enable(True)
		except Exception:
			log(f'addButton error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def delButton(self, sender):  # remove a selected permutation
		try:
			permList = self.w.kernerPane.group0.permList
			index = permList.getSelectedIndexes()[0]
			listToSet = self.w.kernerPane.group0.permList.get()
			try: # try because nothing may be selected
				del listToSet[index]
				self.w.kernerPane.group0.permList.set(listToSet)
			except Exception:
				pass

			# disable delButton if there's only one item: maybe move elsewhere
			if len(listToSet) == 1:
				self.w.kernerPane.group0.delButton.enable(False)
		except Exception:
			log(f'delButton error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def PolyKernMain(self, sender):  # generate kerning
		try:
			self.font.disableUpdateInterface()

			self.w.kernerPane.group1.progress.set(0)
			self.w.kernerPane.group1.progress.show(True)

			for progress in PKCommonLogic.kernOpenType(presetName=self.loadedPresetName):

				self.w.kernerPane.group1.progress.set(progress)

			time.sleep(.5)
			self.w.kernerPane.group1.progress.show(False)

			self.font.enableUpdateInterface()
		except Exception:
			log(f'PolyKernMain error: {traceback.format_exc()}', error=True)

	def interpolateLayer_glyph_interpolation_error_(self, layer: GSLayer, glyph: GSGlyph, interpolation: dict, error: Any):
		pass
		'''
		interpolation = {
			masterID1: 0.2,
			masterID2: 0.8,
		}
		'''
		''' TODO: actuelly implement this:
		otherLayer = glyph.layers[masterID1]

		bubble = otherLayer.bubble
		if bubble is None:
			return

		for bubbleNode in bubble.leftNode:
			bubbleNode.x *= 0.2
			bubbleNode.y *= 0.2
		'''

# Tab1 functions (generate bubbled font)
	@objc.python_method
	def generateBubbledFont(self, sender):

		folderPath = GetFolder(message="Select a saving location.")

		if folderPath:
			exportedPaths = PKExport.writeFontWithBBLH(folderPath, self.font)
			if exportedPaths:
				self.w.hide()
				urls = [NSURL.fileURLWithPath_(p) for p in exportedPaths]
				NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(urls)


	@objc.python_method
	def getHTMLforBBLH(self, sender):
		pass
