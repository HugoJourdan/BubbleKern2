from __future__ import division, print_function, unicode_literals

import objc
from GlyphsApp import Glyphs, GSLayer, GSGlyph, GetFolder, EDIT_MENU #, GSCallbackHandler
from GlyphsApp.plugins import GeneralPlugin
import traceback
import vanilla
import subprocess # for revealing exported font in Finder
import re  # for displaying font file name
import time # for managing progress bar
from typing import Optional, Any
from Foundation import NSMutableDictionary #, NSLog

from AppKit import (
	NSMenu,  # for the BubbleKern submenu
	NSMenuItem,
	NSEventModifierFlagOption,  # for the all-masters variant of a menu item
	NSImage,  # for setting plus and minus button image
	NSFont,  # for setting preview in Menlo
	# NSDragOperationMove,  # currently useless
	NSFloatingWindowLevel,
	NSWorkspace,  # for revealing exported fonts in Finder
	NSURL,  # for revealing exported fonts in Finder
)

import BKAutoBubble
import BKCommonLogic
import BKExport

totalPairsPrefix = 'Total Pairs To Check : '

# Vanilla.Sheet which can be closed upon esc key press
class escapableSheet(vanilla.Sheet):
	def cancelOperation_(self, sender):
		# called when Escape is pressed
		self.close()

# PLUGIN WITH A WINDOW UNDER EDIT TOOL
# 1. GENERATES PRE-COMPUTED KERNING DATA (MOST COMMON USE CASE)
# 2. GENERATES FONT WITH BBLH AND BBLV TABLES (EXPERIMENTAL)
# 3. REMOVES BUBBLE DATA ENTIRELY

# THE BACKEND CODE FOR COMPUTING BUBBLE SHAPES SHOULD BE SHARED WITH THE DRAWING METHODS (IN BKCOMMONLOGIC)


popupOptions = ["New Preset...", "Rename Selected...", "Duplicate Selected...", "Delete Selected..."]

Menlo12 = NSFont.fontWithName_size_("Menlo", 12)


# INITIATE LOGGING
import logging
import os

def _setup_logger():
	logger = logging.getLogger("BubbleKern")

	if logger.handlers:
		return logger  # already configured (important for Glyphs reload)

	logger.setLevel(logging.DEBUG)
	log_path = os.path.expanduser("~/Desktop/Glyphs_BubbleKern.log")
	handler = logging.FileHandler(log_path)
	formatter = logging.Formatter("%(asctime)s BubbleKern: %(message)s")
	handler.setFormatter(formatter)
	logger.addHandler(handler)
	logger.propagate = False  # prevents double logging
	return logger

def log(message:str = '', error: bool = None):
	level = logging.ERROR if error is None else logging.DEBUG
	_setup_logger().log(level, message)

# / INITIATE LOGGING

class BubbleKernKerner(GeneralPlugin):
	name: str
	w: Optional[vanilla.Window] = None

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize({
			'en': 'BubbleKern Kerner…',
			'ja': 'BubbleKern ダイアログ…'
		})

	@objc.python_method
	def start(self):  # STUFF TO UPON GLYPHS STARTUP
		submenu = NSMenu.alloc().initWithTitle_('BubbleKern')
		for title, action in (
			(self.name, self.showWindow_),
			('BubbleKern Settings…', self.openSettings_),
		):
			item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
			item.setTarget_(self)
			submenu.addItem_(item)
		submenu.addItem_(NSMenuItem.separatorItem())

		generate = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Generate Auto Bubbles for Selected Glyphs', self.generateSelected_, '')
		generate.setTarget_(self)
		submenu.addItem_(generate)
		# THE OPTION VARIANT. An alternate takes the place of the item above it
		# while its modifier is held: same key equivalent, different mask.
		everyMaster = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
			'Generate Auto Bubbles for Selected Glyphs for all Masters',
			self.generateAllMasters_, '')
		everyMaster.setTarget_(self)
		everyMaster.setKeyEquivalentModifierMask_(NSEventModifierFlagOption)
		everyMaster.setAlternate_(True)
		submenu.addItem_(everyMaster)

		parent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('BubbleKern', None, '')
		parent.setSubmenu_(submenu)
		Glyphs.menu[EDIT_MENU].append(parent)
		self.registerParameterSheet()

	def registerParameterSheet(self):
		# THE SETTINGS PARAMETER GETS ITS OWN EDITOR. Clicking its value in Font
		# Info opens sliders instead of a text field; the string stays editable
		# by hand for anyone who prefers that.
		try:
			from GlyphsApp import GSCallbackHandler
			import BKAutoBubble
			import BKParameterSheet
			GSCallbackHandler.addCustomParameterSheetController_forParameter_(
				BKParameterSheet.BubbleKernParameterSheet,
				BKAutoBubble.SETTINGS_PARAMETER)
		except Exception:
			BKCommonLogic.log(
				f'BubbleKern parameter sheet not registered: {traceback.format_exc()}',
				error=True)

	def openSettings_(self, sender):
		# The window belongs to the TOOL, which Glyphs instantiates at launch
		# alongside this one - both are principal classes of the same bundle.
		try:
			import BKTool
			if BKTool.mainDrawingHandler is None:
				BKCommonLogic.show_alert('BubbleKern Settings',
					'The BubbleKern tool has not loaded, so its settings cannot open.',
					cancel=False)
				return
			BKTool.mainDrawingHandler.openSettingsWindow()
		except Exception:
			BKCommonLogic.log(f'openSettings error: {traceback.format_exc()}', error=True)

	def generateSelected_(self, sender):
		self.generateBubbles(False)

	def generateAllMasters_(self, sender):
		self.generateBubbles(True)

	@objc.python_method
	def generateBubbles(self, allMasters):
		"""Auto-generate both walls for the selected glyphs."""
		try:
			import BKBubbleStore
			import BKTool
			font = Glyphs.font
			if font is None:
				return
			glyphs, seen = [], set()
			for layer in font.selectedLayers:
				glyph = layer.parent if isinstance(layer, GSLayer) else None
				if glyph is not None and glyph.name not in seen:
					seen.add(glyph.name)
					glyphs.append(glyph)
			masters = font.masters if allMasters else [font.selectedFontMaster]
			layers = [glyph.layers[master.id] for glyph in glyphs for master in masters]
			layers = [layer for layer in layers if layer is not None and layer.name is not None]
			if not layers:
				return
			# THE STORE, NOT THE TOOL. Generating a bubble is writing userData
			# on a layer and needs no canvas; going through the live tool meant
			# this command failed outright when the tool had not been picked up
			# yet. Only the redraw wants the tool, and only if there is one.
			for isLeft in (True, False):
				BKBubbleStore.autoGenerate(font, isLeft, layers=layers)
			if BKTool.mainDrawingHandler is not None:
				BKTool.mainDrawingHandler.refreshAfterWrite()
		except Exception:
			BKCommonLogic.log(f'generateBubbles error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def buildWindow(self):
		self.font = Glyphs.font  # allows the plugin to stick to the initially given font
		self.w = vanilla.Window(
			(230, 500),
			maxSize=(2000, 2000),
			title='BubbleKern Kerner',
			autosaveName="com.Tosche.BubbleKernKerner.mainwindow"  # stores last window position and size
		)

		self.w.bind("should close", self.windowShouldClose_)
		self.w._window.setLevel_(NSFloatingWindowLevel)  # MAKE WINDOW FLOAT
		windowNS = self.w.getNSWindow()
		windowNS.setHidesOnDeactivate_(True)  # MAKE WINDOW HIDE WHILE IN BACKGROUND

		self.w.tabs = vanilla.Tabs('auto', ["Generate Kerning", "Generate Bubbled Fonts", "Remove BubbleKern Data"])

		self.buildKerningTab()
		self.buildFontTab()
		self.buildRemoveTab()

		# LAYOUT WINDOW
		rules = [
			'H:|[tabs(>=100)]|',
			'V:|-[tabs]|',
		]
		self.w.addAutoPosSizeRules(rules, None)

	@objc.python_method
	def buildKerningTab(self):
		"""The presets table and what a run does with it."""
		# GENERATE KERNING TAB
		tab0 = self.w.tabs[0]  # STANDARD KERNIG GENERATION
		tab0.group0 = vanilla.Group('auto')  # TABLES TO MAKE AUTO LAYOUT EASIER
		tab0.group1 = vanilla.Group('auto')  # BUTTONS

		tab0.group0.optionsPopup = vanilla.PopUpButton('auto', popupOptions, callback=self.popupTasks)  # POPUP MENU
		tab0.group0.optionsPopup._nsObject.menu().setAutoenablesItems_(False) # what does it do?

		emptyPermutation = [{"Left": "A B C", "Right": "X Y Z", "Add Flipped": True, "Pairs": "0"}]  # TITLE

		dragSettings = dict(
			makeDragDataCallback=self.makeDragDataCallback
		)
		dropSettings = dict(
			pasteboardTypes=[
				"string",
				"Tosche.BubbleKernKerner.permListIndexes"
			],
			dropCandidateEnteredCallback=self.dropCandidateEnteredCallback,
			dropCandidateCallback=self.dropCandidateCallback,
			performDropCallback=self.performDropCallback
		)

		tab0.group0.permList = vanilla.List2(
			'auto',
			items=emptyPermutation,
			columnDescriptions=[
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

		tableView = tab0.group0.permList._tableView
		tableView.setAllowsColumnReordering_(False)
		tableView.unbind_("sortDescriptors")  # Disables sorting by clicking the title bar
		tableView.tableColumns()[0].setResizingMask_(1)
		tableView.tableColumns()[1].setResizingMask_(1)
		tableView.tableColumns()[2].setResizingMask_(0)
		tableView.tableColumns()[3].setResizingMask_(0)
		tableView.setColumnAutoresizingStyle_(1)
		# setResizingMask_() 0=Fixed, 1=Auto-Resizable (Not user-resizable). There may be more options?
		# setColumnAutoresizingStyle accepts value from 0 to 5.
		# For detail,see: http://api.monobjc.net/html/T_Monobjc_AppKit_NSTableViewColumnAutoresizingStyle.htm


		tab0.group0.preview = vanilla.TextEditor('auto', "", readOnly=True)
		tab0.group0.preview._textView.setFont_(Menlo12)
		tab0.group0.total = vanilla.TextBox('auto', totalPairsPrefix, alignment="right", sizeStyle="small")

		# ADD & DELETE BUTTONS:
		plusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
		tab0.group0.addButton = vanilla.ImageButton('auto', imageObject=plusImage, callback=self.addButton)
		minusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("trash", None)
		tab0.group0.delButton = vanilla.ImageButton('auto', imageObject=minusImage, callback=self.delButton)

		rules = [
			'H:|-[optionsPopup]',
			'H:|-[permList(>=600)][preview(200)]-|',
			'H:|-[addButton(iconButtonW)][delButton(iconButtonW)]-[total][preview]',
			'V:|[optionsPopup]-[permList(>=100)][addButton(iconButtonH)]|',
			'V:[permList][delButton(iconButtonH)]',
			'V:[permList]-(8)-[total(iconButtonH)]',
			'V:[optionsPopup]-[preview][addButton(iconButtonH)]',
		]
		metrics = {'iconButtonW': 40, 'iconButtonH': 24}
		tab0.group0.addAutoPosSizeRules(rules, metrics)

		tab0.group1.progress = vanilla.ProgressBar('auto', maxValue=100)
		tab0.group1.progress.show(False)
		# THE PAIRS THAT ACTUALLY OCCUR. A preset is a cartesian product and
		# most of it never turns up in text; the list beside this plugin says
		# which combinations do. It narrows the preset rather than replacing
		# it, so the rows still decide which glyphs are in scope.
		tab0.group1.relevantOnly = vanilla.CheckBox('auto', 'Only the most relevant pairs',
			value=bool(BKAutoBubble._pref(BKAutoBubble.PREF_RELEVANT_ONLY, False)),
			callback=self.toggleRelevantOnly, sizeStyle='small')
		tab0.group1.relevantOnly.getNSButton().setToolTip_(
			'Kern only the pairs that occur in running text, after André '
			'Fuchs\u2019s kerning-pairs')
		# WHAT A RUN PUTS IN THE FONT, ASKED WHERE THE RUN IS STARTED - not in
		# the settings window, which is about what a bubble is shaped like. A
		# wall does not change because the pair it kerns was written under a
		# group name.
		tab0.group1.writeGroups = vanilla.CheckBox('auto', 'Write groups, not pairs',
			value=bool(BKAutoBubble._pref(BKAutoBubble.PREF_KERN_GROUPS, False)),
			callback=self.toggleWriteGroups, sizeStyle='small')
		tab0.group1.writeGroups.getNSButton().setToolTip_(
			'Kern the groups the bubbles fall into, so one pair covers every '
			'glyph that shares a wall')
		tab0.group1.allButton = vanilla.Button('auto', "Kern All Pairs", sizeStyle="regular", callback=self.BubbleKernMain)
		tab0.group1.selButton = vanilla.Button('auto', "Kern Pairs for Selected Glyphs", sizeStyle="regular", callback=self.BubbleKernMain)
		rules = [
			'H:|-[relevantOnly]-[writeGroups]-[progress]-[allButton(==selButton)]-[selButton]-|',
			'V:|-(12)-[relevantOnly(18)]',
			'V:|-(12)-[writeGroups(18)]',
			'V:|-(8)-[progress]-|',
			'V:|-(8)-[allButton]-|',
			'V:|-(8)-[selButton]-|',
		]
		tab0.group1.addAutoPosSizeRules(rules, metrics)

		rules = [
			'H:|[group0(>=100)]|',
			'H:|[group1(>=100)]|',
			'V:|[group0][group1]|',
		]
		tab0.addAutoPosSizeRules(rules, None)

	@objc.python_method
	def buildFontTab(self):
		"""Exporting a font with the bubbles baked in as BBLH."""
		# GENERATE FONT TAB
		tab1 = self.w.tabs[1]
		tab1.caption = vanilla.TextBox('auto', """This feature is EXPERIMENTAL and may not work as expected.

1. You can generate a new font with 'BBLH' table based on the BubbleKern data.
(Maybe also vertical 'BBLV' table in the future)

2. You need to have FontTools installed.
Install it in Glyphs Python using this Terminal command: "pip install fonttools"

3. Interpolation is currently not supported. Only the instances matching masters will be exported.

4. The font format is set in the "Export..." menu.""")
		tab1.exportButton = vanilla.Button('auto', 'Generate Bubbled Font', self.generateBubbledFont)
		tab1.getHTMLButton = vanilla.Button('auto', 'Get HTML tester', self.getHTMLforBBLH)
		tab1.getHTMLButton.enable(False)
		tab1.spacer0 = vanilla.Group('auto')
		tab1.spacer1 = vanilla.Group('auto')
		tab1.spacer2 = vanilla.Group('auto')
		tab1.spacer3 = vanilla.Group('auto')
		rules = [
			'H:|[spacer0(==spacer1)]-[caption]-[spacer1]|',
			'H:|[spacer0(==spacer1)]-[exportButton]-[spacer1]|',
			'H:|[spacer0(==spacer1)]-[getHTMLButton]-[spacer1]|',
			'V:|[spacer2(==spacer3)]-[caption]-(20)-[exportButton]-[getHTMLButton]-[spacer3]|',
		]
		tab1.addAutoPosSizeRules(rules, None)

	@objc.python_method
	def buildRemoveTab(self):
		"""Taking every trace of BubbleKern back out of the font."""
		# REMOVE BUBBLEKERN TAB
		tab2 = self.w.tabs[2]
		filepath = self.font.filepath
		fileName = '(%s)' % re.sub('.*/', '', filepath) if filepath is not None else ''
		tab2.message = vanilla.TextBox('auto', f"Here, you can remove BubbleKern data from the font:\n\n{self.font.familyName} {fileName}")
		tab2.button = vanilla.Button('auto', 'Remove; yes I am absolutely sure.', self.removeBubbles)
		tab2.spacer0 = vanilla.Group('auto')
		tab2.spacer1 = vanilla.Group('auto')
		tab2.spacer2 = vanilla.Group('auto')
		tab2.spacer3 = vanilla.Group('auto')
		rules = [
			'H:|[spacer0(==spacer1)]-[message]-[spacer1]|',
			'H:|[spacer0(==spacer1)]-[button]-[spacer1]|',
			'V:|[spacer2(==spacer3)]-[message]-(20)-[button]-[spacer3]|',
		]
		tab2.addAutoPosSizeRules(rules, None)

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
				newName = BKCommonLogic.show_alert('Enter Name for new Preset.', askString=True)
				if not newName:
					return
				if newName in self.presetsDic.keys():
					BKCommonLogic.show_alert('Duplicate name is not allowed.', cancel=False)
					return
				# empty names are already handled in show_alert
				self.loadedPresetName = newName
				self.savePreferences(option=2) # 2 = new
				self.refreshPopupButton()
				self.loadPreferences()

			elif index == presetsDicLength + 1: # rename
				newName = BKCommonLogic.show_alert(f'Enter New Name for the Preset: {self.loadedPresetName}', askString=True)
				if not newName:
					return
				self.presetsDic[newName] = self.presetsDic.pop(self.loadedPresetName) # remove and return the same dic entry
				self.loadedPresetName = newName
				self.savePreferences()
				self.refreshPopupButton()
			
			elif index == presetsDicLength + 2: # duplicate
				newName = BKCommonLogic.show_alert(f'Enter Name for the Duplicate of Preset: {self.loadedPresetName}', askString=True)
				if not newName:
					return
				if newName in self.presetsDic.keys():
					BKCommonLogic.show_alert('Existing preset name is not allowed.', cancel=False)
					return
				self.presetsDic[newName] = self.presetsDic[self.loadedPresetName] # just copy the same dic entry
				self.loadedPresetName = newName
				self.savePreferences()
				self.refreshPopupButton()
				self.loadPreferences()

			elif index == presetsDicLength + 3: # delete
				if len(self.presetsDic) <= 1: # only one or zero preset to delete
					BKCommonLogic.show_alert("You can't delete the last preset.", cancel=False)
					self.w.tabs[0].group0.optionsPopup.set(0)
				else:
					deleting = BKCommonLogic.show_alert(f'Are you sure you want to delete "{self.loadedPresetName}"?')
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
			thePopup = self.w.tabs[0].group0.optionsPopup

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
				presetsDic = Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"]
			except Exception: # if old BubbleKern is being used
				presetsDic = Glyphs.defaults["com.Tosche.BubbleKern.favDic"]
				del Glyphs.defaults["com.Tosche.BubbleKern.favDic"]
				Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"] = presetsDic

			# I need NSMutableDictionary to modify dictionary; without it, I cannot change teh content
			self.presetsDic = NSMutableDictionary.alloc().initWithDictionary_copyItems_(presetsDic, True)

			if Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"] is None:
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

				Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"] = self.presetsDic
			else:  # presetsDic exists, but not validated
				pass

			# which dic to set
			if sender == self.w.tabs[0].group0.optionsPopup:
				log('Popup is loading')
			elif sender == self.w.tabs[0].group0.permList:  # the permList has been edited
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
					pairsCount = self.pairsCount(perm[0], perm[1], perm[2])
					dictToSet['Pairs'] = pairsCount
					permutations.append(dictToSet)
				self.w.tabs[0].group0.permList.set(permutations)

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
				Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"] = self.presetsDic
				# need to load something
				self.loadPreferences()
			elif option == 2: # making new list
				self.presetsDic[self.loadedPresetName] = [('A B C', 'X Y Z', True)]
			else: # saving
				permList = self.w.tabs[0].group0.permList.get()
				perms = []
				for item in permList: # for each line
					perm = []
					perm.append(item['Left'])
					perm.append(item['Right'])
					perm.append(item['Add Flipped'])
					perms.append(perm)
				self.presetsDic[self.loadedPresetName] = perms

			Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"] = self.presetsDic
		except Exception:
			log(f'SavePreferences error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def pairsCount(self, text0: str, text1: str, flipped: bool) -> int:
		multiply = 2 if flipped else 1
		return len(self.cleanUpText(text0)) * len(self.cleanUpText(text1)) * multiply

	@objc.python_method
	def refreshPreview(self): # preview EditText
		try:
			permList = self.w.tabs[0].group0.permList
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
			self.w.tabs[0].group0.preview.set(lines)
		except Exception:
			log(f'refreshPreview error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def toggleRelevantOnly(self, sender=None):
		try:
			Glyphs.defaults[BKAutoBubble.PREF_RELEVANT_ONLY] = bool(sender.get())
			self.refreshTotal()
		except Exception:
			log(f'toggleRelevantOnly error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def toggleWriteGroups(self, sender=None):
		try:
			Glyphs.defaults[BKAutoBubble.PREF_KERN_GROUPS] = bool(sender.get())
		except Exception:
			log(f'toggleWriteGroups error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def relevantCount(self, permutations) -> int:
		"""How many of the preset's pairs the relevant list keeps. -> int

		Counted the same way the kerner builds them, rather than from the row
		totals: those are a product per row, and duplicates across rows only
		show up once the pairs are actually made.
		"""
		try:
			font = self.font
			if font is None:
				return 0
			relevant = BKAutoBubble.relevant_pair_names(
				BKCommonLogic.namesByCharacter(font))
			pairs = set()
			for row in permutations:
				lefts = self.cleanUpText(row['Left'])
				rights = self.cleanUpText(row['Right'])
				pairs.update((left, right) for left in lefts for right in rights)
				if row['Add Flipped']:
					pairs.update((right, left) for left in lefts for right in rights)
			return len(pairs & relevant)
		except Exception:
			log(f'relevantCount error: {traceback.format_exc()}', error=True)
			return 0

	@objc.python_method
	def refreshTotal(self): # preview EditText
		try:
			permutations = self.w.tabs[0].group0.permList.get()
			if bool(BKAutoBubble._pref(BKAutoBubble.PREF_RELEVANT_ONLY, False)):
				totalPairs = self.relevantCount(permutations)
			else:
				totalPairs = sum([int(p['Pairs']) for p in permutations])
			self.w.tabs[0].group0.total.set(totalPairsPrefix + format(totalPairs, ','))
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
		groupView = self.w.tabs[0].group0.getNSView()
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
				permListUI = self.w.tabs[0].group0.permList
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
			permList = self.w.tabs[0].group0.permList

			indexes = [index]

			typesAndValues = {
				"str": permList.get()[index],
				"Tosche.BubbleKernKerner.permListIndexes": indexes
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
		if source == self.w.tabs[0].group0.permList:
			return "move"
		return "copy"

	@objc.python_method
	def performDropCallback(self, info):
		try:
			sender = info["sender"]
			source = info["source"]
			endIndex = info["index"] # proposed drop index
			items = info["items"]

			permList = self.w.tabs[0].group0.permList

			# reorder
			if source == permList:
				# indexes = original indexes of items being carried.
				indexes = sender.getDropItemValues(items, "Tosche.BubbleKernKerner.permListIndexes")[0]
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
			permList = self.w.tabs[0].group0.permList
			listToSet = permList.get()
			listToSet += [{'Left': 'A B C', 'Right': 'X Y Z', 'Add Flipped': True, "Pairs": "0"}]
			permList.set(listToSet)

			# enable delButton if there's multiple: maybe move elsewhere
			if len(listToSet) > 1:
				self.w.tabs[0].group0.delButton.enable(True)
		except Exception:
			log(f'addButton error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def delButton(self, sender):  # remove a selected permutation
		try:
			permList = self.w.tabs[0].group0.permList
			index = permList.getSelectedIndexes()[0]
			listToSet = self.w.tabs[0].group0.permList.get()
			try: # try because nothing may be selected
				del listToSet[index]
				self.w.tabs[0].group0.permList.set(listToSet)
			except Exception:
				pass

			# disable delButton if there's only one item: maybe move elsewhere
			if len(listToSet) == 1:
				self.w.tabs[0].group0.delButton.enable(False)
		except Exception:
			log(f'delButton error: {traceback.format_exc()}', error=True)

	@objc.python_method
	def BubbleKernMain(self, sender):  # generate kerning
		try:
			self.font.disableUpdateInterface()

			selGlyphs = True if sender == self.w.tabs[0].group1.selButton else False

			self.w.tabs[0].group1.progress.set(0)
			self.w.tabs[0].group1.progress.show(True)

			for progress in BKCommonLogic.kernOpenType(presetName=self.loadedPresetName, selectedLayersOnly=selGlyphs):

				self.w.tabs[0].group1.progress.set(progress)

			time.sleep(.5)
			self.w.tabs[0].group1.progress.show(False)

			self.font.enableUpdateInterface()
		except Exception:
			log(f'BubbleKernMain error: {traceback.format_exc()}', error=True)

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
			exportedPaths = BKExport.writeFontWithBBLH(folderPath, self.font)
			if exportedPaths:
				self.w.hide()
				urls = [NSURL.fileURLWithPath_(p) for p in exportedPaths]
				NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_(urls)


	@objc.python_method
	def getHTMLforBBLH(self, sender):
		pass

# Tab2 functions (remove bubble data)
	@objc.python_method
	def removeBubbles(self, sender):
		try:
			self.font
			del self.font.userData['useBubbleKern']
			try:
				del self.font.tempData['useBubbleKern']
			except Exception:
				pass

			keys = (
				'BubbleKernExportL', 'BubbleKernExportR',
				'BubbleKernReferL', 'BubbleKernReferR',
				'BubbleKernNodesL', 'BubbleKernNodesR'
			)
			for g in self.font.glyphs:
				for gl in g.layers:
					for key in keys:
						try:
							del gl.userData[key]
						except Exception:
							pass
					try:
						del gl.tempData['bubbles']
					except Exception:
						pass
		except Exception:
			pass
