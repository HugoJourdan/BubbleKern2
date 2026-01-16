from __future__ import division, print_function, unicode_literals

import objc
from GlyphsApp import Glyphs, GSLayer, GSGlyph, GSCallbackHandler, EDIT_MENU
from GlyphsApp.plugins import GeneralPlugin
import traceback
import vanilla
from typing import Optional, Any

from AppKit import (
	NSMenuItem,
	NSImage,  # for setting plus and minus button image
	NSFont,  # for setting preview in Menlo
	NSDragOperationMove,  # currently useless
	NSFloatingWindowLevel,
)

# PLUGIN WITH A WINDOW UNDER EDIT TOOL
# 1. GENERATES PRE-COMPUTED KERNING DATA (MOST COMMON USE CASE)
# 2. GENERATES FONT WITH BBLH AND BBLV TABLES (EXPERIMENTAL)
# 3. REMOVES BUBBLE DATA ENTIRELY

# THE BACKEND CODE FOR COMPUTING BUBBLE SHAPES SHOULD BE SHARED WITH THE DRAWING METHODS (IN BKCOMMONLOGIC)

tab0options = [
	"Options",
	"  New Set",
	"  Save Set in Favourites...",
	"  Delete Set from Favourites...",
	"Favourites",
]
Menlo12 = NSFont.fontWithName_size_("Menlo", 12)

# currently useless
toolOrderDragType = "toolOrderDragType"

class BubbleKernKerner(GeneralPlugin):
	name: str
	w: Optional[vanilla.Window] = None

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize({
			'en': 'BubbleKern Kerner…',
			'ja': 'BubbleKern ダイアログ…'
		})
		# GSCallbackHandler.addCallback_forOperation_(self, "GSPrepareLayerCallback")

	@objc.python_method
	def start(self):  # STUFF TO UPON GLYPHS STARTUP
		newMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(self.name, self.showWindow_, "")
		newMenuItem.setTarget_(self)
		Glyphs.menu[EDIT_MENU].append(newMenuItem)

	def buildWindow(self):
		# self.font = Glyphs.font  # allows the plugin to stick to the initially given font
		self.w = vanilla.Window(
			(230, 500),
			# minSize=(200, 300),
			# maxSize=(230, 2000),
			title='BubbleKern Kerner',
			autosaveName="com.Tosche.BubbleKernKerner.mainwindow"  # stores last window position and size
		)

		self.w._window.setLevel_(NSFloatingWindowLevel)  # MAKE WINDOW FLOAT
		windowNS = self.w.getNSWindow()
		windowNS.setHidesOnDeactivate_(True)  # MAKE WINDOW HIDE WHILE IN BACKGROUND

		self.w.tabs = vanilla.Tabs('auto', ["Generate Kerning", "Generate Bubbled Fonts", "Remove Bubbles"])

		# GENERATE KERNING TAB
		tab0 = self.w.tabs[0]  # STANDARD KERNIG GENERATION
		tab0.group0 = vanilla.Group('auto')  # TABLES TO MAKE AUTO LAYOUT EASIER
		tab0.group1 = vanilla.Group('auto')  # BUTTONS
		tab0.group0.options = vanilla.PopUpButton('auto', tab0options, callback=self.optionTasks)  # POPUP MENU
		tab0.group0.options._nsObject.menu().setAutoenablesItems_(False)
		emptyPermutation = [{"Left": "", "Right": "", "Add Flipped": "", "Pairs": "0"}]  # TITLE
		spX = 10
		prevX = 180
		GroupColumnWidth = int((self.w.getPosSize()[2] - 180 - spX * 5 - prevX) / 2 + 1)
		tab0.group0.permList = vanilla.List(
			'auto',
			emptyPermutation,
			columnDescriptions=[
				{"title": "Left", "width": GroupColumnWidth},
				{"title": "Right", "width": GroupColumnWidth},
				{
					"title": "Add Flipped",
					"cell": vanilla.CheckBoxListCell(),
					"width": 70,
				},
				{"title": "Pair Count", "width": 90},
			],
			#  dragSettings = dict( type=NSString, callback=self.dragCallback ), # WHY DOES THIS THING NOT WORK?
			selfDropSettings=dict(
				type=toolOrderDragType,
				operation=NSDragOperationMove,
				callback=self.dropListSelfCallback,
			),
			allowsMultipleSelection=False,
			selectionCallback=self.permListSelected,
			doubleClickCallback=self.permListDoubleClick,
		)

		tableView = tab0.group0.permList._tableView
		tableView.setAllowsColumnReordering_(False)
		tableView.unbind_("sortDescriptors")  # Disables sorting by clicking the title bar
		tableView.tableColumns()[0].setResizingMask_(1)
		tableView.tableColumns()[1].setResizingMask_(1)
		tableView.tableColumns()[2].setResizingMask_(0)
		tableView.tableColumns()[3].setResizingMask_(0)
		# tableView.tableColumns()[4].setResizingMask_(0)
		tableView.setColumnAutoresizingStyle_(1)
		# setResizingMask_() 0=Fixed, 1=Auto-Resizable (Not user-resizable). There may be more options?
		# setColumnAutoresizingStyle accepts value from 0 to 5.
		# For detail,see: http://api.monobjc.net/html/T_Monobjc_AppKit_NSTableViewColumnAutoresizingStyle.htm

		tab0.group0.sectionPreviewCaption = vanilla.TextBox('auto', "Section Preview", sizeStyle="small")
		tab0.group0.preview = vanilla.TextEditor('auto', "", readOnly=True)
		tab0.group0.preview._textView.setFont_(Menlo12)
		tab0.group0.total = vanilla.TextBox('auto', "", sizeStyle="small")

		# ADD & DELETE BUTTONS:
		plusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
		tab0.group0.addButton = vanilla.ImageButton('auto', imageObject=plusImage, callback=self.addButton)
		minusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("minus", None)
		tab0.group0.delButton = vanilla.ImageButton('auto', imageObject=minusImage, callback=self.delButton)

		rules = [
			'H:|-(margin)-[options]-[sectionPreviewCaption]-(margin)-|',
			'H:|-(margin)-[permList(800)]-[preview]-(margin)-|',
			'H:|-(margin)-[addButton]-[delButton]-[total]-(margin)-|',

			'V:|-(margin)-[options]-[permList(800)]-[addButton]-(margin)-|',
			'V:|-(margin)-[options]-[permList(800)]-[delButton]-(margin)-|',
			'V:|-(margin)-[options]-[permList(800)]-(margin)-|',
			'V:|-[permList(800)]-(margin)-|',
			'V:|-(margin)-[permList]-[total]-(margin)-|',
			'V:|-(margin)-[sectionPreviewCaption]-[preview]-(margin)-|',
		]
		metrics = {'margin': 10}
		tab0.group0.addAutoPosSizeRules(rules, metrics)

		tab0.group1.allButton = vanilla.Button('auto', "Kern All Pairs", sizeStyle="regular", callback=self.BubbleKernMain)
		tab0.group1.selButton = vanilla.Button('auto', "Kern Pairs for Selected Glyphs", sizeStyle="regular", callback=self.BubbleKernMain)
		rules = [
			'H:|-(margin)-[allButton]-[selButton]-(margin)-|',
			'V:|-(margin)-[allButton]-(margin)-|',
			'V:|-(margin)-[selButton]-(margin)-|',
		]
		metrics = {'margin': 10}
		tab0.group1.addAutoPosSizeRules(rules, metrics)

		rules = [
			'H:|[group0]|',
			'H:|[group1]|',
			'V:|[group0][group1]|',
		]
		tab0.addAutoPosSizeRules(rules, None)

		# GENERATE FONT TAB
		# tab1 = self.w.tabs[1]

		# LAYOUT WINDOW
		rules = [
			'H:|[tabs]|',
			'V:|[tabs]|',
		]
		self.w.addAutoPosSizeRules(rules, None)

		# self.loadPrefs()

	def showWindow_(self, sender):
		if self.w is None:
			self.buildWindow()

		try:
			if self.w is not None:
				self.w.open()
		except:
			print(traceback.format_exc())

	def updatePresetsButton(self):  # refresh option popup items
		try:
			favNameList = self.favNameList()
			self.w.tabs[0].options.setItems(tab0options + favNameList)
			menu = self.w.tabs[0].options._nsObject.menu()
			menu.itemAtIndex_(0).setEnabled_(False)
			divider0 = NSMenuItem.separatorItem()
			menu.insertItem_atIndex_(divider0, 6)
			menu.itemAtIndex_(7).setEnabled_(False)
		except Exception as e:
			Glyphs.showMacroWindow()
			print("BubbleKern Error (refreshOptions): %s" % e)

	@objc.python_method
	def optionTasks(self, sender):  # dealing with presets popup
		pass

	@objc.python_method
	def permListSelected(self, sender):  # when permutation list line has been selected
		pass

	@objc.python_method
	def permListDoubleClick(self, sender):  # when permutation list line has been double-clicked
		pass

	@objc.python_method
	def dropListSelfCallback(self, sender):  # when drag item has been dropped. not working
		pass

	@objc.python_method
	def addButton(self, sender):  # add a permutation
		pass

	@objc.python_method
	def delButton(self, sender):  # remove a selected permutation
		pass

	@objc.python_method
	def BubbleKernMain(self, sender):  # generate kerning
		pass

	def interpolateLayer_glyph_interpolation_error_(self, layer: GSLayer, glyph: GSGlyph, interpolation: dict, error: Any):
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
