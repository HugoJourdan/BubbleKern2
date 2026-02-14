from __future__ import division, print_function, unicode_literals

import objc
from GlyphsApp import Glyphs, GSLayer, GSGlyph, GSCallbackHandler, EDIT_MENU
from GlyphsApp.plugins import GeneralPlugin
import traceback
import vanilla
import re # for displaying font file name
from typing import Optional, Any

from Foundation import NSMutableDictionary
from AppKit import (
	NSMenuItem,
	NSImage,  # for setting plus and minus button image
	NSFont,  # for setting preview in Menlo
	NSDragOperationMove,  # currently useless
	NSFloatingWindowLevel,
)

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

popupOptions = ["New Set", "Rename Set...", "Delete Set..."]

Menlo12 = NSFont.fontWithName_size_("Menlo", 12)

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

	@objc.python_method
	def buildWindow(self):
		self.font = Glyphs.font  # allows the plugin to stick to the initially given font
		self.w = vanilla.Window(
			(230, 500),
			# minSize=(200, 300),
			maxSize=(2000, 2000),
			title='BubbleKern Kerner',
			autosaveName="com.Tosche.BubbleKernKerner.mainwindow"  # stores last window position and size
		)

		self.w.bind("should close", self.windowShouldClose_)
		self.w._window.setLevel_(NSFloatingWindowLevel)  # MAKE WINDOW FLOAT
		windowNS = self.w.getNSWindow()
		windowNS.setHidesOnDeactivate_(True)  # MAKE WINDOW HIDE WHILE IN BACKGROUND

		self.w.tabs = vanilla.Tabs('auto', ["Generate Kerning", "Generate Bubbled Fonts", "Remove BubbleKern Data"])

		# GENERATE KERNING TAB
		tab0 = self.w.tabs[0]  # STANDARD KERNIG GENERATION
		tab0.group0 = vanilla.Group('auto')  # TABLES TO MAKE AUTO LAYOUT EASIER
		tab0.group1 = vanilla.Group('auto')  # BUTTONS
		
		tab0.group0.optionsPopup = vanilla.PopUpButton('auto', popupOptions, callback=self.popupTasks)  # POPUP MENU
		# tab0.group0.optionsPopup._nsObject.menu().setAutoenablesItems_(False) # what does it do?

		emptyPermutation = [{"Left": "", "Right": "", "Add Flipped": "", "Pairs": "0"}]  # TITLE
		# spX = 10
		# prevX = 180
		# GroupColumnWidth = int((self.w.getPosSize()[2] - 180 - spX * 5 - prevX) / 2 + 1)
		tab0.group0.permList = vanilla.List(
			'auto',
			emptyPermutation,
			columnDescriptions=[
				{"title": "Left",},
				{"title": "Right",},
				{
					"title": "Add Flipped",
					"cell": vanilla.CheckBoxListCell(),
					"width": 70,
				},
				{"title": "Pair Count", "width": 90},
			],
			#  dragSettings = dict( type=NSString, callback=self.dragCallback ), # WHY DOES THIS THING NOT WORK?
			# toolOrderDragType = "toolOrderDragType"
			selfDropSettings=dict(
				type="toolOrderDragType",
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


		# tab0.group0.sectionPreviewCaption = vanilla.TextBox('auto', "Section Preview", sizeStyle="small")
		tab0.group0.preview = vanilla.TextEditor('auto', "Total : ", readOnly=True)
		tab0.group0.preview._textView.setFont_(Menlo12)
		tab0.group0.total = vanilla.TextBox('auto', "", sizeStyle="small")

		# ADD & DELETE BUTTONS:
		plusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
		tab0.group0.addButton = vanilla.ImageButton('auto', imageObject=plusImage, callback=self.addButton)
		minusImage = NSImage.imageWithSystemSymbolName_accessibilityDescription_("trash", None)
		tab0.group0.delButton = vanilla.ImageButton('auto', imageObject=minusImage, callback=self.delButton)
		
		tab0.group0.spacer0 = vanilla.Group('auto')
		tab0.group0.spacer1 = vanilla.Group('auto')
		tab0.group0.spacer2 = vanilla.Group('auto')

		rules = [
			'H:|-(margin)-[optionsPopup]-[spacer0(>=100)]-(margin)-|',
			'H:|-(margin)-[permList(>=600)][preview(150)]-(margin)-|',
			'H:|-(margin)-[addButton(iconButton)][delButton(iconButton)]-[spacer1(>=100)]-[total][spacer2(150)]-(margin)-|',
	
			'V:|-(margin)-[optionsPopup]-[permList(>=100)][addButton(iconButton)]|',
			'V:|-(margin)-[optionsPopup]-[permList(>=100)][delButton(iconButton)]|',
			'V:|-(margin)-[optionsPopup]-[permList(>=100)][spacer1(iconButton)]|',
			'V:|-(margin)-[spacer0]-[permList(>=100)][spacer1(iconButton)]|',
			'V:|-(margin)-[spacer0]-[permList(>=100)][total(iconButton)]|',
			'V:|-(margin)-[spacer0]-[preview(>=100)][spacer2(iconButton)]|',
		]
		metrics = {'margin': 10, 'iconButton':24}
		tab0.group0.addAutoPosSizeRules(rules, metrics)

		tab0.group1.spacer0 = vanilla.Group('auto')
		tab0.group1.allButton = vanilla.Button('auto', "Kern All Pairs", sizeStyle="regular", callback=self.BubbleKernMain)
		tab0.group1.selButton = vanilla.Button('auto', "Kern Pairs for Selected Glyphs", sizeStyle="regular", callback=self.BubbleKernMain)
		rules = [
			'H:|-(margin)-[spacer0(>=100)][allButton(==selButton)]-[selButton]-(margin)-|',
			'V:|-(margin)-[spacer0]-(margin)-|',
			'V:|-(margin)-[allButton]-(margin)-|',
			'V:|-(margin)-[selButton]-(margin)-|',
		]
		metrics = {'margin': 10}
		tab0.group1.addAutoPosSizeRules(rules, metrics)

		rules = [
			'H:|[group0(>=100)]|',
			'H:|[group1(>=100)]|',
			'V:|[group0][group1]|',
		]
		tab0.addAutoPosSizeRules(rules, None)

		# GENERATE FONT TAB
		# tab1 = self.w.tabs[1]

		# REMOVE BUBBLEKERN TAB
		tab2 = self.w.tabs[2]
		filepath = self.font.filepath
		fileName = '(%s)' % re.sub('.*/','',filepath) if filepath != None else ''
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

		# LAYOUT WINDOW
		rules = [
			'H:|[tabs(>=100)]|',
			'V:|-[tabs]|',
		]
		self.w.addAutoPosSizeRules(rules, None)

		# self.refreshOptions() # load popup
		self.loadPreferences() # load permList

	def showWindow_(self, sender):
		try:
			self.font = Glyphs.font
			if self.font is None: # no open font
				return
			if self.w is None: # no open window yet
				self.buildWindow()
			
			self.w.open()
		except:
			print(traceback.format_exc())

	def windowShouldClose_(self, sender): # User attempts to close the main window
		self.w.hide() # hide the window instead of closing
		return False   # IMPORTANT: prevents actual close

	# def updatePresetsButton(self):  # refresh option popup items
	# 	try:
	# 		favNameList = self.favNameList()
	# 		self.w.tabs[0].options.setItems(tab0options + favNameList)
	# 		menu = self.w.tabs[0].options._nsObject.menu()
	# 		menu.itemAtIndex_(0).setEnabled_(False)
	# 		divider0 = NSMenuItem.separatorItem()
	# 		menu.insertItem_atIndex_(divider0, 6)
	# 		menu.itemAtIndex_(7).setEnabled_(False)
	# 	except:
	# 		print("BubbleKern Error (refreshOptions):", traceback.format_exc())

	@objc.python_method
	def popupTasks(self, sender):  # dealing with presets popup
		index = sender.get()
		print("popup selected", index)
		# items = sender.getItems()
		# print("selected item:", items[index] if 0 <= index < len(items) else "INVALID INDEX")
		# print("all items:", items)

		# print("popup selected", sender.get())
		# self.loadPreferences(sender)
		pass

	@objc.python_method
	def refreshOptions(self):  # refresh option popup items
		try:
			favDic = Glyphs.defaults["com.Tosche.BubbleKern.favDic"]
			favDicNames = [k for k in favDic.keys()]
			thePopup = self.w.tabs[0].group0.optionsPopup

			# favNameList = self.favNameList()
			thePopup.setItems( favDicNames + popupOptions )

			# add separator
			menu = thePopup._nsObject.menu()
			# menu.itemAtIndex_(0).setEnabled_(False) # from old implementation
			divider0 = NSMenuItem.separatorItem()
			menu.insertItem_atIndex_(divider0, len(favDic))
			menu.itemAtIndex_( len(favDic)+1 ).setEnabled_(False) # disable separator

		except Exception as e:
			Glyphs.showMacroWindow()
			print("BubbleKern Error (refreshOptions): %s" % e)

	@objc.python_method
	def loadPreferences(self, sender=None):
		try:
			permListUI = self.w.tabs[0].group0.permList
			favDic = Glyphs.defaults["com.Tosche.BubbleKern.favDic"]

			if Glyphs.defaults["com.Tosche.BubbleKern.favDic"] == None:
				# Fallback to default favourite dictionary
				favDic = {
					"Sample": (
						(
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z", # Left
							"A B C D E F G H I J K L M N O P Q R S T U V W X Y Z", # Right
							False, # add flipped
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
				Glyphs.defaults["com.Tosche.BubbleKern.favDic"] = favDic
			else: # favDic exists, but not validated
				pass
			# favDic = NSMutableDictionary.alloc().initWithDictionary_copyItems_(favDic, True)

			# which dic to set
			if sender == self.w.tabs[0].group0.optionsPopup:
				print(sender.get())
			else: # the permList has been edited
				pass
				# print('Hello!', sender)
		except: 
			print("BubbleKern Error (loadPreferences):", traceback.format_exc())

	@objc.python_method
	def SavePreferences(self, sender):
		# rewrite as if it's called everyt time permList is dragged, or list content edited
		try:
			permList = []
			permListUI = self.w.tabs[0].group0.permList
			for item in permListUI.get():
				print(item)
# 			for i in range(len(self.w.tabs[0].permList)): # get it right
# 				perm = []
# 				perm.append(self.w.tabs[0].permList[i]["Left"])
# 				perm.append(self.w.tabs[0].permList[i]["Right"])
# 				perm.append(self.w.tabs[0].permList[i]["Add Flipped"])
# 				permList.append(perm)
# 			favDic[permutationName] = permList

	# 		Glyphs.defaults["com.Tosche.BubbleKern.favDic"] = favDic
		except:
			print("BubbleKern Error (SavePreferences):", traceback.format_exc())

	@objc.python_method
	def permListSelected(self, sender):  # when permutation list line has been selected
		pass

	@objc.python_method
	def permListDoubleClick(self, sender):  # when permutation list line has been double-clicked, open sheet
		try:
			permListUI = self.w.tabs[0].group0.permList
			# print(permListUI.get())

			groupText0 = sender[sender.getSelection()[0]]["Left"]
			groupText1 = sender[sender.getSelection()[0]]["Right"]
			self.s = escapableSheet((600, 600), self.w)
			self.s.label0 = vanilla.TextBox('auto', "Left of pair", sizeStyle="small")
			self.s.label1 = vanilla.TextBox('auto', "Right or pair", sizeStyle="small")
			self.s.edit0 = vanilla.TextEditor('auto', groupText0)
			self.s.edit0._textView.setFont_(Menlo12)
			self.s.edit1 = vanilla.TextEditor('auto', groupText1)
			self.s.edit1._textView.setFont_(Menlo12)
			self.s.instruction = vanilla.TextBox('auto',"Enter list of glyph names; they can be separated by space, slash, comma, tab, or line break.")
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
		except IndexError:
			pass

	@objc.python_method
	def cancelEditPermutation(self,sender): # Close sheet by clicking cancel (esc is implemented as subclass)
		try:
			self.s.close()
		except:
			print(traceback.format_exc())

	@objc.python_method
	def cleanUpText(self, text) -> str:  # Function to clean up the glyph name list in Sheet
		try:
			text = re.sub("[/,\n\t]", " ", text)
			text = text.split() # turn to a list
			return '/n'.join(text)
		except:  # The text wasn't ascii-decodable. Probably not a string of glyph names.
			print('cleanUpText error: ', traceback.format_exc())
			return text

	@objc.python_method
	def confirmEditPermutation(self, sender):
		try:
			# update items

			text1 = self.s.edit0.get()
			text2 = self.s.edit1.get()
			newText1 = self.cleanUpText(text1)
			newText2 = self.cleanUpText(text2)
			if newText1 == False or newText2 == False:
				# Message('', "Invalid text!")
				pass
			else:
				permListUI = self.w.tabs[0].group0.permList
				i = permListUI.getSelection()[0]
				permListUI[i]["Left"] = newText1
				permListUI[i]["Right"] = newText2
				self.s.close()
				self.refreshSectionPreview(i)

		except:
			print(traceback.format_exc())

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

	@objc.python_method
	def removeBubbles(self, sender):
		try:
			self.font
			del(self.font.userData['useBubbleKern'])

			keys = ('BubbleKernExportL', 'BubbleKernExportR',
				'BubbleKernReferL', 'BubbleKernReferR',
				'BubbleKernNodesL', 'BubbleKernNodesR')
			for g in self.font.glyphs:
				for gl in g.layers:
					for key in keys:
						try:
							del(gl.userData[key])
						except:
							pass
		except:
			pass