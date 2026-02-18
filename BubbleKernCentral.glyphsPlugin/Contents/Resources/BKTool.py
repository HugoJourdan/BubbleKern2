# THE TOOL BASED ON SELECTTOOL FOR EDITING BUBBLES.

import objc
import traceback
from math import radians, tan, hypot
import vanilla
from GlyphsApp import Glyphs, GSLayer, GSCallbackHandler, distance, addPoints, UPDATEINTERFACE, DRAWBACKGROUND, DRAWINACTIVE
from GlyphsApp.plugins import SelectTool
from Cocoa import (
	NSObject,
	NSAttributedString,  # for drawing node coordinates
	NSFontAttributeName,  # for drawing node coordinates
	NSFont,  # for drawing node coordinates
	NSForegroundColorAttributeName,  # for drawing node coordinates
	# NSMenuItem,  # for contextual menu item
	NSColor,  # for highlighting in draw calls
	NSBezierPath,  # for many things
	NSPoint,  # for many things
	# NSRect,  # to get the circular dot for drawing nodes
	NSMakeRect,  # to get the circular dot for drawing nodes
	# NSSize, # doesn't seem to be used
	# NSEventModifierFlagDeviceIndependentFlagsMask,  # for doing stuff in mouseDown_() and keyDown_()
	# NSEventModifierFlagShift,  # for doing stuff in mouseDown_() and keyDown_()
	NSEventModifierFlagShift, NSEventModifierFlagCommand, NSEventModifierFlagOption,  # for doing stuff in mouseDown_() and keyDown_()
	NSAlert,
	NSAlertStyleCritical,
)

from typing import Self

from BKCommonLogic import getFinalBubble, show_alert

DEBUG_COORDS = True  # set to False to reduce logging

# constants
fontSize = 12
clickRadius = 10

TempDataBubblesKey = "bubbles"
TempDataLeftNodesKey = 'nodesL'
TempDataLeftIsDefaultKey = 'defaultL'
TempDataRightNodesKey = 'nodesR'
TempDataRightIsDefaultKey = 'defaultR'

# UI STUFF FOR DISPLAYING INFO BOX
# Patched Vanilla Group class to generate Info Box
GSInspectorView = objc.lookUpClass("GSInspectorView")
class InspectorGroup(vanilla.Group):
	nsViewClass = GSInspectorView

# UI STUFF FOR SHOWING DIALOG, IT MAY COME IN HANDY
# def show_alert(message: str, secondMessage: str = ''):
# 	alert = NSAlert.alloc().init()
# 	alert.setMessageText_(message)
# 	if secondMessage != '':
# 		alert.setInformativeText_(secondMessage)
# 	alert.addButtonWithTitle_("OK")  # index 1000
# 	alert.addButtonWithTitle_("Cancel")  # index 1001
# 	alert.setAlertStyle_(NSAlertStyleCritical)
# 	response = alert.runModal()
# 	if response == 1000:  # OK
# 		return True
# 	elif response == 1001:  # Cancel
# 		return False

class BubbleNode(NSObject):

	_position: NSPoint = NSPoint(0, 0)
	selected: bool = False

	@objc.typedSelector(b"{CGPoint=dd}@:")
	def position(self):
		return self._position

	@objc.typedSelector(b"v@:{CGPoint=dd}")
	def setPosition_(self, position):
		self._position = position

	@property
	def pos(self):
		return self._position

	@pos.setter
	def pos(self, pos):
		self._position = pos

	@property
	def x(self):
		return self._position.x

	@property
	def y(self):
		return self._position.y

	def __repr__(self):
		return f"(BubbleNode(0x{id(self):x}) x={self.pos.x}, y={self.pos.y})"

	def description(self):
		return f"(BubbleNode(0x{id(self):x}) x={self.pos.x}, y={self.pos.y})"

	def parent(self):
		return None

	def copy(self) -> Self:
		copy = self.__class__.new()
		copy.pos = self._position
		return copy

def makeBubbleNode(x, y, italicAngle, xHeight):
	node = BubbleNode.alloc().init()
	if italicAngle != 0:
		italicAngle = radians(90 + italicAngle)
		newX = x - (y - xHeight / 2) / tan(italicAngle)
	else:
		newX = x
	node.setPosition_(NSPoint(round(newX), round(y)))
	return node

def tempToUserNodeX(x, y, italicAngle, xHeight):
	if italicAngle != 0:
		italicAngle = radians(90 - italicAngle)
		return x - (y - xHeight / 2) / tan(italicAngle)
	else:
		return x

# def handleAtPosition(position):
# 	handle = BubbleNode.new()
# 	handle.setPosition_(position)
# 	return handle



# USED TO CHECK IF NODE IS CLICKABLE.
def nearNodes(point0, point1, threshold):
	d = distance(point0, point1)
	return d <= threshold

# ONLY USED IN closestToNodes
def closest_point_on_segment(A: BubbleNode, B: BubbleNode, P: NSPoint):  # A=node0, B=node1, P=clicked point
	x1, y1 = A.pos.x, A.pos.y
	x2, y2 = B.pos.x, B.pos.y
	x0, y0 = P.x, P.y
	dx = x2 - x1  # s distance
	dy = y2 - y1  # y disance

	if dx == 0 and dy == 0:  # A and B are the same point
		return A.pos.x, A.pos.y
	# Projection parameter t
	t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
	# Clamp to segment
	t = max(0, min(1, t))
	# Closest point
	closest_x = x1 + t * dx
	closest_y = y1 + t * dy

	return closest_x, closest_y

# FOR CHECKING IF mousePos ADDS A NEW NODE.
# CHECKS IF mousePos IS ON THE SERIES OF SEGMENTS COMPOSED OF 'NODES'.
# ASSUMES 'NODES' STARTS FROM BOTTOM
def closestToNodes(nodes: list[BubbleNode], mousePos: NSPoint):
	if nodes[-1].pos.y < mousePos.y:  # if cursor is too far above the bubble
		return nodes[-1].pos.x, nodes[-1].pos.y
	elif nodes[0].pos.y > mousePos.y:  # if too far below the bubble
		return nodes[0].pos.x, nodes[0].pos.y
	else:
		for i, n in enumerate(nodes):
			if n != nodes[-1]:
				if n.pos.y <= mousePos.y <= nodes[i + 1].pos.y:  # mousePos Y is between these two nodes
					return closest_point_on_segment(n, nodes[i + 1], mousePos)
	return None

# FOR DISPLAYING COORDFINATES. RETURNS ITALIC-OFFSET X VALUE FOR A GIVEN NODE.
def italicOffset(node, angle, xHeight):
	try:
		angle = radians(90 - angle)
		newX = node.x - (node.y - xHeight / 2) / tan(angle)
		return newX
	except:
		return 0


mainDrawingHandler = None
bubbleDrawingIsActive = False  # True if I want to draw all the time

class BubbleKernTool(SelectTool):
	bubbles: dict[str, list[BubbleNode]]

	@objc.python_method
	def settings(self):
		global mainDrawingHandler
		if mainDrawingHandler is None:
			mainDrawingHandler = self
			GSCallbackHandler.addCallback_forOperation_(mainDrawingHandler, DRAWBACKGROUND)
			GSCallbackHandler.addCallback_forOperation_(mainDrawingHandler, DRAWINACTIVE)

		self.name = Glyphs.localize({
			"en": "BubbleKern Tool",
		})
		# self.generalContextMenus = [
		# 	{
		# 		'name': Glyphs.localize({
		# 			'en': 'BubbleKern Menu :',
		# 		}),
		# 		'action': None
		# 	},
		# 	{
		# 		'name': Glyphs.localize({
		# 			'en': 'Lock Node to Sidebearing',
		# 		}),
		# 		'action': self.lockNodeToSB_
		# 	},
		# ]
		self.keyboardShortcutModifier = (NSEventModifierFlagCommand | NSEventModifierFlagShift | NSEventModifierFlagOption)
		self.keyboardShortcut = 'b'
		self.toolbarPosition = 20
		self.horizontal = getattr(self, "horizontal", True)  # whether horizontal or vertical bubbles
		self.closestNode = None  # for highlighting the addable node
		self.selectableNode = None  # for highlighting the selectable node
		# imported from copilot code
		# self._mouseDownPos = getattr(self, "_mouseDownPos", (0.0, 0.0)) # to track the start of mouse down when dragging
		# self._dragging = getattr(self, "_dragging", False) # boolean whether bing moved
		# self._dragging_nodes = getattr(self, "_dragging_nodes", []) # node being moved (convert to plural?)
		# self._drag_offset = getattr(self, "_drag_offset", (0.0, 0.0)) # dragging box

		# USER INTERFACE
		self.w = vanilla.Window((360, 10))
		self.w.group = InspectorGroup("auto")
		self.w.group.glyphNameL = vanilla.EditText('auto', '', callback=self.infoBox, placeholder='Copy glyph')
		self.w.group.line = vanilla.VerticalLine('auto')
		self.w.group.glyphNameR = vanilla.EditText('auto', '', callback=self.infoBox, placeholder='Copy glyph')
		f0 = self.w.group.glyphNameL.getNSTextField()
		f1 = self.w.group.glyphNameR.getNSTextField()
		f0.setNextKeyView_(f1)
		f1.setNextKeyView_(f0)
		menuItems = [
			dict(title='Auto-Generate Bubble', callback=None),
			dict(title='Decompose Refered', callback=None),
			dict(title='Reset Bubble', callback=None),
			dict(title='Erase Bubble', callback=self.eraseBubble),
			dict(title='Show Compatibility', callback=None),
			dict(title='Show Node Coordinates', callback=None)
		]
		self.w.group.exportL = vanilla.CheckBox('auto', 'Export', callback=self.infoBox)
		self.w.group.exportR = vanilla.CheckBox('auto', 'Export', callback=self.infoBox)
		self.w.group.menusL = vanilla.ActionButton('auto', menuItems)
		self.w.group.menusR = vanilla.ActionButton('auto', menuItems)
		rules = (
			'H:|-(pad)-[glyphNameL(glyphNameR)]-[line]-[glyphNameR]-(pad)-|',
			'H:|-(pad)-[exportL]-[menusL]-[line]-[exportR]-[menusR]-(pad)-|',
			'V:|-(pad)-[glyphNameL]-(sp)-[exportL]-(pad)-|',
			'V:|-(pad)-[glyphNameL]-(sp)-[menusL]-(pad)-|',
			'V:|[line]|',
			'V:|-(pad)-[glyphNameR]-(sp)-[exportR]-(pad)-|',
			'V:|-(pad)-[glyphNameR]-(sp)-[menusR]-(pad)-|',
		)
		metrics = {'pad': 8, 'sp': 8}
		self.w.group.addAutoPosSizeRules(rules, metrics)
		self.infoBoxView = self.w.group.getNSView()
		self.inspectorDialogView = True
		# / USER INTERFACE

	@objc.python_method
	def start(self):  # WHEN GLYPHSAPP STARTS
		pass

	# @objc.python_method
	# def initialDialog(self):
	# 	try:
	# 		alertTitle = 'Starting BubbleKern'
	# 		alertMessage = """Are you sure you want to use BubbleKern in this font?
	# 		(You can remove font's Bubble data from Edit > BubbleKern Kerner)"""
	# 		initialise = show_alert(message = alertTitle, secondMessage = alertMessage)
	# 	except:
	# 		print(traceback.format_exc())

	@objc.python_method
	def activate(self):  # When the tool is activated, updateUI and set activeLayer
		try:
			proceed = False
			initialise = False
			f = Glyphs.font

			# check if initial dialog is necessary
			use = f.tempData['useBubbleKern'] # if user has already clicked Yes or Cancel in the dialog
			if use == None: # if no pre-existing answer in userData
				use = f.userData['useBubbleKern']

			if use == True: # BubbleKern already in use
				proceed = True
			elif use == None: # on the first run per font file
				alertTitle = 'Starting BubbleKern'
				alertMessage = """Are you sure you want to use BubbleKern in this font?
				(You can remove font's Bubble data from Edit > BubbleKern Kerner)"""
				initialise = show_alert(message = alertTitle, secondMessage = alertMessage)
			elif use == False:
				Glyphs.showNotification("BubbleKern Tool", "If you want to use BubbleKern, please reopen the file.")

			if proceed or initialise: # standard proceed
				f.tempData['useBubbleKern'] = True
				f.userData['useBubbleKern'] = True
				Glyphs.addCallback(self.updateUI, UPDATEINTERFACE)
				self.activeLayer = self.editViewController().activeLayer()
			else: # Cancel has been clicked or use is already False, go to Select Tool
				f.tempData['useBubbleKern'] = False
				self.deactivate()
				f.tool = 'SelectTool'

			if initialise:
				for g in f.glyphs:
					for gl in g.layers:
						self.saveNodesToLayer(gl)
						gl.userData['BubbleKernExportL'] = 1
						gl.userData['BubbleKernExportR'] = 1
		except:
			print(traceback.format_exc())

	@objc.python_method
	def deactivate(self):  # When the tool is deactivated / went to font view
		# print('deactivate called')
		Glyphs.removeCallback(self.updateUI, UPDATEINTERFACE)
		pass

	@objc.python_method
	def setActiveLayer(self):
		if self.editViewController() is None:
			return None
		elif self.editViewController().activeLayer().name is None:
			return None
		else:
			self.activeLayer = self.editViewController().activeLayer()
			return True

	@objc.python_method
	def infoBox(self, sender):  # Called if Info Box UI elements are edited
		try:
			controller = self.editViewController()
			self.activeLayer = controller.activeLayer()
			self.saveInfoToLayer(self.activeLayer)
			Glyphs.redraw()
		except:
			print('infoBox error', traceback.print_exc())

	@objc.python_method
	def updateUI(self, theEvent):  # Fill UI fields from userData after Interface change
		try:
			if self.setActiveLayer() is None:
				return
			layer = self.activeLayer
			value = layer.userData['BubbleKernReferL']
			if (isinstance(value, str) and len(value) == 0) or not value:
				value = ''
			self.w.group.glyphNameL.set(value)
			value = layer.userData['BubbleKernReferR']
			if (isinstance(value, str) and len(value) == 0) or not value:
				value = ''
			self.w.group.glyphNameR.set(value)
			self.w.group.exportL.set(bool(layer.userData['BubbleKernExportL']))
			self.w.group.exportR.set(bool(layer.userData['BubbleKernExportR']))
		except:
			print('updateUI error', traceback.print_exc())

	def view(self):  # SHOWS INFO BOX; CALLED CONSTANTLY
		# RETURN NONE WHEN YOU WANT TO DISABLE INFO BOX
		return self.infoBoxView

	@objc.python_method
	def infoForLayer(self, layer):  # RETURNS exportL, exportR, referL, referR
		userData = layer.userData
		exportL = bool(userData.get("BubbleKernExportL", True))
		exportR = bool(userData.get("BubbleKernExportR", True))

		referL = userData.get("BubbleKernReferL", None)
		if isinstance(referL, str) and len(referL) == 0:
			referL = None
		referR = userData.get("BubbleKernReferR", None)
		if isinstance(referR, str) and len(referR) == 0:
			referR = None
		return exportL, exportR, referL, referR

	@objc.python_method
	def saveInfoToLayer(self, layer):  # CALLED AFTER UI CHANGE. SAVES "INHERIT" AND "EXPORT" STATUS TO LAYER USERDATA
		if layer.name is None:
			return
		
		# SAVE INTERFACE'S GLYPH NAME, L
		value = self.w.group.glyphNameL.get()
		if isinstance(value, str) and len(value) == 0:
			value = None
		if layer.userData['BubbleKernReferL'] is not value:
			# IF USERDATA AND UI FIELD DISAGREE, DELETE TEMP DATA
			del layer.tempData[TempDataBubblesKey]

		if value:  # SAVE
			layer.userData['BubbleKernReferL'] = value
		else:  # REMOVE REFERENCE IF UI IS EMPTY
			del layer.userData['BubbleKernReferL']

		# REPEAT THE ABOVE FOR R
		value = self.w.group.glyphNameR.get()
		if isinstance(value, str) and len(value) == 0:
			value = None
		if layer.userData['BubbleKernReferR'] is not value:
			del layer.tempData[TempDataBubblesKey]
		if value:
			layer.userData['BubbleKernReferR'] = value
		else:
			del layer.userData['BubbleKernReferR']

		# SAVE INTERFACE'S EXPORT STATUS, L
		value = self.w.group.exportL.get()
		if value:
			layer.userData['BubbleKernExportL'] = int(value)
		else:  # REMOVE REFERENCE IF UI IS EMPTY
			del layer.userData['BubbleKernExportL']

		# REPEAT THE ABOVE FOR R
		value = self.w.group.exportR.get()
		if value:
			layer.userData['BubbleKernExportR'] = int(value)
		else:
			del layer.userData['BubbleKernExportR']

	@objc.python_method
	def saveNodesToLayer(self, layer):  # SAVES NODES TO LAYER USERDATA
		m = layer.master
		italicAngle, xHeight = m.italicAngle, m.xHeight
		bubbles = layer.tempData[TempDataBubblesKey]  # bubble tempData may not exist yet
		value = bubbles[TempDataLeftNodesKey] if bubbles else None

		if value:
			value = sorted(value, key=lambda node: node.y)  # SORT NODES BY HEIGHT

			# fix italic offset when transferring from tempData to userData
			userDataValue = []
			for n in value:
				userDataValue.append((int(round(tempToUserNodeX(n.x, n.y, italicAngle, xHeight))), int(round(n.y))))
			layer.userData['BubbleKernNodesL'] = userDataValue
			# layer.userData['BubbleKernNodesL'] = [[int(round(n.pos.x)), int(round(n.pos.y))] for n in value]
			# SAVE BACK TO REFLECT THE REORDERED NODES
			layer.tempData[TempDataBubblesKey][TempDataLeftNodesKey] = value
		else:
			# del layer.userData['BubbleKernNodesL']
			layer.userData['BubbleKernNodesL'] = [(0, m.descender), (0, m.ascender)]

		# RIGHT SIDE SHOULD SUBTRACT LAYER WIFTH
		value = bubbles[TempDataRightNodesKey] if bubbles else None
		if value:
			value = sorted(value, key=lambda node: node.y)  # SORT NODES BY HEIGHT
			userDataValue = []
			for n in value:
				userDataValue.append((int(round(tempToUserNodeX(n.x, n.y, italicAngle, xHeight) - layer.width)), int(round(n.y))))
			layer.userData['BubbleKernNodesR'] = userDataValue
			# layer.userData['BubbleKernNodesR'] = [[int(round(n.pos.x - layer.width)), int(round(n.pos.y))] for n in value]
			layer.tempData[TempDataBubblesKey][TempDataRightNodesKey] = value
		else:
			# del layer.userData['BubbleKernNodesR']
			layer.userData['BubbleKernNodesR'] = [(0, m.descender), (0, m.ascender)]

		# print("__save", layer.userData)

	# LOAD BUBBLE FROM LAYER'S USERDATA. OPTIOINALLY LOAD TO TEMPDATA IF LAYER IS ACTIVE.
	@objc.python_method
	def loadNodesFromLayer(self, layer=None, forceLoad=False, master=None) -> dict | None:
		try:
			if layer.name is None:
				return None
				# layer = self.editViewController().activeLayer()

			bubbles: dict | None = layer.tempData[TempDataBubblesKey]  # i.e. ['bubbles']
			if not forceLoad:
				if bubbles:
					prevWidth = int(bubbles['width'])
					if prevWidth != int(layer.width):
						# print("__!!!reset bubble", prevWidth, int(layer.width))
						bubbles = None
				if bubbles:
					return bubbles  # raw bubble data

			if master is None:
				master = layer.associatedFontMaster()

			# if there's no tempData to return, rely on userData
			userData = layer.userData
			exportL, exportR, referL, referR = self.infoForLayer(layer)

			nodesL = userData.get("BubbleKernNodesL", None)
			nodesR = userData.get("BubbleKernNodesR", None)

			# if no bubbles present, make up one and save to Temp Data (not User)
			bubbles = {}
			if not nodesL:
				nodesL = [(0, master.descender), (0, master.ascender)]
				bubbles[TempDataLeftIsDefaultKey] = True
			if not nodesR:
				nodesR = [(0, master.descender), (0, master.ascender)]
				bubbles[TempDataRightIsDefaultKey] = True

			# IT USED TO LOAD NODES FROM REFERRED LAYERS, BUT I FIND NO USE FOR THAT
			# if referL:
			# 	otherGlyph = layer.font().glyphs[referL] # referred glyph
			# 	if otherGlyph: # if referred glyph exists
			# 		otherLayer = otherGlyph.layers[master.id]
			# 		otherUserData = otherLayer.userData
			# 		otherNodesL = otherUserData.get("BubbleKernNodesL", None)
			# 		if otherNodesL:
			# 			nodesL = otherNodesL
			# if referR:
			# 	otherGlyph = layer.font().glyphs[referR]
			# 	if otherGlyph:
			# 		otherLayer = otherGlyph.layers[master.id]
			# 		otherUserData = otherLayer.userData
			# 		otherNodesR = otherUserData.get("BubbleKernNodesR", None)
			# 		if otherNodesR:
			# 			nodesR = otherNodesR

			bubbles[TempDataLeftNodesKey] = [makeBubbleNode(n[0], n[1], master.italicAngle, master.xHeight) for n in nodesL]
			# # nodesR'S X VALUES ARE BASED ON LAYER WIDTH WHEN SAVED
			# # IN self.bubbles TEMP DATA, THEY ARE ACTUAL VALUES
			bubbles[TempDataRightNodesKey] = [makeBubbleNode(n[0] + layer.width, n[1], master.italicAngle, master.xHeight) for n in nodesR]
			bubbles['width'] = layer.width

			layer.tempData[TempDataBubblesKey] = bubbles  # set raw bubbles in tempData

			return bubbles
		except:
			print('bubble load failed')
			print(traceback.print_exc())
			return {}

	@objc.python_method
	def foreground(self, layer):  # layer to draw nodes

		# if Glyphs.isActive() is False: # SKIP DRAWING IF GLYPHS IS NOT IN FRONT. REALLY NECESSARY?
		# 	return
		if Glyphs.font.tool != self.__class__.__name__ or layer.name is None:  # 'BubbleKernTool'
			return
		try:
			graphicView = self.editViewController().graphicView()
			scale = graphicView.scale()

			diameter = 10 / scale  # size of node
			diameter *= pow(scale, 0.1)
			radius = diameter / 2

			bubbles: dict = layer.tempData[TempDataBubblesKey]
			if bubbles is None:
				return
			# italicAngle = layer.master.italicAngle
			# xHeight = layer.master.xHeight

			_, _, referL, referR = self.infoForLayer(layer)

			drawNodesL = not referL and not layer.isAligned
			drawNodesR = not referR and not layer.isAligned

			nodesL = bubbles[TempDataLeftNodesKey]
			nodesR = bubbles[TempDataRightNodesKey]

			# DRAW REGULAR NODES
			# print('nodes', nodesL, nodesR)
			for nodes in (nodesL, nodesR):
				if nodes == nodesL:
					if drawNodesL is False:
						continue
					NSColor.systemCyanColor().set()
				else:
					if drawNodesR is False:
						continue
					NSColor.systemPinkColor().set()
				# print('reaching here')
				for n in nodes:
					rect = NSMakeRect(n.pos.x - radius, n.pos.y - radius, diameter, diameter)
					path = NSBezierPath.bezierPathWithOvalInRect_(rect)
					path.setLineWidth_(1.2 / scale)
					path.stroke()


			# HIGHLIGHT SELECTION
			#if layer == self.activeLayer:
			for nodes in (nodesL, nodesR):
				if nodes == nodesL:
					if drawNodesL is False:
						continue
					NSColor.systemCyanColor().set()
				else:
					if drawNodesR is False:
						continue
					NSColor.systemPinkColor().set()
				for n in nodes:
					# if n.selected:
					if n in layer.selection:
						rect = NSMakeRect(n.pos.x - radius, n.pos.y - radius, diameter, diameter)
						path = NSBezierPath.bezierPathWithOvalInRect_(rect)
						path.fill()

				# DISPLAY COORDINATES WHEN SELECTED
				fontAttributes = {
					#NSFontAttributeName: NSFont.labelFontOfSize_(10.0),
					NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(fontSize / scale, 0.0),
					NSForegroundColorAttributeName: NSColor.textColor()
				}
				for n in nodesL + nodesR:
					if n in layer.selection:
						newX = tempToUserNodeX(n.x, n.y, layer.master.italicAngle, layer.master.xHeight)
						newX = newX - bubbles['width'] if n in nodesR else newX
						coordinates = f'{int(round(newX))}, {int(round(n.y))}'
						displayText = NSAttributedString.alloc().initWithString_attributes_(
							coordinates,
							fontAttributes
						)
						# if coordinatesOption == 0: # show at bottom left
						textAlignment = 0
						# bottom left: 0, bottom center: 1, bottom right: 2
						# center left: 3, center center: 4, center right: 5
						# top left: 6, top center: 7, top right: 8
						displayLocation = NSPoint(n.x + 10, n.y + 10)
						displayText.drawAtPoint_alignment_(displayLocation, textAlignment)

			# HIGHLIGHT NODES CLOSE TO MOUSE CURSOR

			if self.closestNode is not None:  # if mouseMoved_() says there's a add-able node on a line
				color = NSColor.systemGrayColor().colorWithAlphaComponent_(0.75)
				color.set()
				n = self.closestNode
				rect = NSMakeRect(n[0] - radius, n[1] - radius, diameter, diameter)
				path = NSBezierPath.bezierPathWithOvalInRect_(rect)
				path.setLineWidth_(1 / scale)
				path.stroke()

		except:
			print(traceback.print_exc())

	def drawBackgroundForLayer_options_(self, layer, options):  # run drawBubbleWalls()
		'''
		options = {
			"Scale":0.12
			"Black":True/False
		}
		'''
		# print('active current tool =', Glyphs.font.tool)
		if Glyphs.font.tool == self.__class__.__name__ and layer.name is not None: # 'BubbleKernTool'
			# print('Drawing active layer', layer.parent)
			self.drawBubbleWalls(layer, True, options)

	def drawBackgroundForInactiveLayer_options_(self, layer, options):  # run drawBubbleWalls()
		# print('inactive current tool =', Glyphs.font.tool)
		if Glyphs.font.tool == self.__class__.__name__ and layer.name is not None: # 'BubbleKernTool'
			# print('Drawing inactive', layer.parent)
			self.drawBubbleWalls(layer, False, options)

	@objc.python_method
	def drawBubbleWalls(self, layer, active, drawOptions):  # draws the bubble
		try:
			if layer.name is None:
				return
			if layer.isAligned:  # IF COMPONENTS ARE AUTO-ALIGNED. DRAW PRE-COMPOSED BUBBLES
				pass
			else:  # COMPONENT NOT AUTO-ALIGNED
				forceLoadState = False if active is True else True
				bubbles: dict | None = self.loadNodesFromLayer(layer, forceLoad=forceLoadState)
				if not bubbles:
					return
				scale = drawOptions["Scale"].doubleValue()
				# print('bubbleWalls', layer, bubbles)

				# bubbleL, bubbleR = layer.userData['BubbleKernNodesL'], layer.userData['BubbleKernNodesR']
				for side in (TempDataLeftNodesKey, TempDataRightNodesKey):
					# SET COLOURS CYAN/PINK
					if side == TempDataLeftNodesKey:
						if not active and bubbles.get(TempDataLeftIsDefaultKey, False):  # don’t draw default bubble in inactive layers
							continue
						color = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
					else:
						if not active and bubbles.get(TempDataRightIsDefaultKey, False):  # don’t draw default bubble in inactive layers
							continue
						color = NSColor.systemPinkColor().colorWithAlphaComponent_(0.5)
					color.set()

					# MAYBE SUBSTITUTE WITH COMMON LOGIC CODE (NOT FINISHED)
					# nodes = bubbles.get(side)
					# if nodes:
					# 	bubblePath = NSBezierPath.alloc().init()
					# 	for i, n in enumerate(nodes):
					# 		if i == 0:  # if first node
					# 			bubblePath.moveToPoint_(n.pos)
					# 		else:
					# 			bubblePath.lineToPoint_(n.pos)
					# 	if active is True:  # WHEN IN BACKGROUND
					# 		bubblePath.setLineWidth_(1.5 / scale)
					# 	else:
					# 		bubblePath.setLineWidth_(1 / scale)
					# 	bubblePath.stroke()

					isLeft = True if side == TempDataLeftNodesKey else False
					bubblePath = getFinalBubble(layer, isLeft)
					
					if active is True:  # WHEN IN BACKGROUND
						bubblePath.setLineWidth_(1.5 / scale)
					else:
						bubblePath.setLineWidth_(1 / scale)
					bubblePath.stroke()

		except Exception:
			print("drawBubbleWalls error: " + traceback.format_exc())

	def mouseMoved_(self, theEvent):
		objc.super(BubbleKernTool, self).mouseMoved_(theEvent)

		try:
			controller = self.editViewController()
			graphicView = controller.graphicView()
			scale = graphicView.scale()

			layer = graphicView.activeLayer()
			if layer.name is None:
				return

			mousePos = graphicView.getActiveLocation_(theEvent)  # pos relative to active layer
			mpx, mpy = mousePos.x, mousePos.y
			clickRadiusAbsolute = clickRadius / scale  # click radius
			# highlight possible click position
			# highlight possible selectable node
			# print(layer.parent.name)
			bubbles = layer.tempData[TempDataBubblesKey]

			_, _, referL, referR = self.infoForLayer(layer)

			# nodesL, nodesR = bubbles['nodesL'], bubbles['nodesR']
			allNodes = []
			if not referL:
				nodesL = bubbles['nodesL']
				allNodes.extend(nodesL)
			if not referR:
				nodesR = bubbles['nodesR']
				allNodes.extend(nodesR)

			# highlight clickable node
			for n in allNodes:
				if nearNodes(n.pos, mousePos, clickRadiusAbsolute):
					#self.selectableNode = n  # for highlighting the selectable node
					if self.closestNode:
						self.closestNode = None  # for highlighting the addable node
						controller.redraw()
					return

			# highlight possible node add position
			if not referL:
				closestL = closestToNodes(nodesL, mousePos)  # two coordinate numbers, not .x and .y
			else:
				closestL = None
			if not referR:
				closestR = closestToNodes(nodesR, mousePos)
			else:
				closestR = None

			if closestL:
				closestDeltaL = hypot(mpx - closestL[0], mpy - closestL[1])
			else:
				closestDeltaL = 100000
			if closestR:
				closestDeltaR = hypot(mpx - closestR[0], mpy - closestR[1])
			else:
				closestDeltaR = 100000
			if closestDeltaL <= clickRadiusAbsolute:  # if L is within radius
				if closestDeltaL <= closestDeltaR:  # if L is closer than R
					closest = closestL
				else:  # if R is closer (R should already be True)
					closest = closestR
			elif closestDeltaR <= clickRadiusAbsolute:  # if R is the only one within radius
				closest = closestR
			else:
				closest = None

			# if closest node is close enough to mouse cursor
			self.closestNode = closest  # for highlighting the addable node
			controller.redraw()

		except:
			# It throws error when not in Glyphs, not worth paying attention
			print("mouseMoved_ error: " + traceback.format_exc())

	# CALLED WHEN MOUSE MOVES OR CLICKS
	def elementAtPoint_atLayer_ignoreLocked_(self, point, layer, ignoreLocked):
		graphicView = self.editViewController().graphicView()
		scale = graphicView.scale()
		clickRadiusAbsolute = clickRadius / scale  # click radius
		# highlight possible click position
		# highlight possible selectable node
		_, _, referL, referR = self.infoForLayer(layer)

		bubbles = self.loadNodesFromLayer(layer)
		if not bubbles:
			return None

		allNodes = []
		if not referL:
			allNodes.extend(bubbles[TempDataLeftNodesKey])
		if not referR:
			allNodes.extend(bubbles[TempDataRightNodesKey])

		# nodesL, nodesR = bubbles[TempDataLeftNodesKey], bubbles[TempDataRightNodesKey]
		# allNodes = []
		# if not referL:
		# 	allNodes.extend(nodesL)
		# if not referR:
		# 	allNodes.extend(nodesR)

		# highlight clickable node
		for n in allNodes:
			if nearNodes(n.pos, point, clickRadiusAbsolute):
				return n
		return None

	# CALLED AFTER DRAGGING EMPTY SPACE FOR MODIFYING SELECTION. SEEMS TO BE WORKING
	def elementsInPath_atLayer_modifier_(self, bezierPath: NSBezierPath, layer: GSLayer, modifierFlag: int):
		bubbles = self.loadNodesFromLayer(layer)
		if not bubbles:
			return None
		nodesL, nodesR = bubbles[TempDataLeftNodesKey], bubbles[TempDataRightNodesKey]
		_, _, referL, referR = self.infoForLayer(layer)

		allNodes = []
		if not referL:
			allNodes.extend(nodesL)
		if not referR:
			allNodes.extend(nodesR)

		nodes = []
		# highlight clickable node
		for n in allNodes:
			if bezierPath.containsPoint_(n.pos):
				nodes.append(n)
		return nodes

	# def mouseDragged_(self, theEvent):
	# 	print('mouseDragged_')

	# CALLED WHILE DRAGGING SELECTED NODES
	def moveSelectionWithPoint_withModifier_(self, offset: NSPoint, modifierFlag: int):
		self.setActiveLayer()
		layer = self.activeLayer
		bubbles = layer.tempData[TempDataBubblesKey]
		controller = self.editViewController()
		shadowLayer = controller.shadowLayer()
		shadowBubbles = self.loadNodesFromLayer(shadowLayer, master=layer.associatedFontMaster())

		# graphicView = self.editViewController().graphicView()
		# self._mouseDownPos = graphicView.getActiveLocation_(theEvent)
		# clickPosition = graphicView.getActiveLocation_(theEvent)
		# print(self._mouseDownPos)

		if not shadowBubbles:
			return
		didChangeAnything = False
		_, _, referL, referR = self.infoForLayer(layer)
		for side in (TempDataLeftNodesKey, TempDataRightNodesKey):
			if side is TempDataLeftNodesKey and referL:
				continue
			if side is TempDataRightNodesKey and referR:
				continue

			nodes = bubbles.get(side, [])
			shadowNodes = shadowBubbles.get(side, [])
			# print(layer.parent.name)
			# print(f'nodes = {nodes}')
			# print(f'shadowNodes = {shadowNodes}')
			# print()
			for node in nodes:
				# THIS IS A PROBLEM AS IDS ONLY MATCH THE FIRST TIME
				if node not in layer.selection:
					continue

				index = nodes.index(node)
				shadowNode = shadowNodes[index]
				pos = shadowNode.pos
				# pos = node.pos
				pos = addPoints(pos, offset)
				node.pos = NSPoint(round(pos.x), round(pos.y))
				didChangeAnything = True
			# print(bubbles)
		if didChangeAnything:
			# print('redrawing')
			# controller.redraw()
			Glyphs.redraw()

	def mouseUp_(self, theEvent):
		try:
			objc.super(BubbleKernTool, self).mouseUp_(theEvent)  # Let Glyphs do its default mouseUp_
			self.setActiveLayer()
			# print('LAYER', self.activeLayer.parent.name)
			self.saveNodesToLayer(self.activeLayer)
			# print('LAYER AFTER SAVE', self.activeLayer.parent.name)
			self.loadNodesFromLayer(self.activeLayer)
			# print('LAYER AFTER LOAD', self.activeLayer.parent.name)
			Glyphs.redraw()
		except:
			print("mouseUp_ error: " + traceback.format_exc())

	# def mouseUp_(self, theEvent):
	# 	graphicView = self.editViewController().graphicView()
	# 	if layer := graphicView.activeLayer():
	# 		self.saveNodesToLayer(self.activeLayer)
	# 		self.loadNodesFromLayer(self.activeLayer, forceLoad=True)
	# 		print('mouseUp_', self.activeLayer)

	def mouseDown_(self, theEvent):
		try:
			# print('mouseDown')
			if theEvent.clickCount() > 1:
				objc.super(BubbleKernTool, self).mouseDown_(theEvent)
				return

			controller = self.editViewController()
			graphicView = controller.graphicView()

			if layer := graphicView.activeLayer():
				m = layer.associatedFontMaster()
				scale = graphicView.scale()
				clickPosition = graphicView.getActiveLocation_(theEvent)
				cpx, cpy = clickPosition.x, clickPosition.y

				# if DEBUG_COORDS:
				# 	print(f"mouseDown_: computed layer_pt=({cpx:.2f},{cpy:.2f})")

				# hit_radius_layer = self._pixel_radius_to_layer(HIT_PIXEL_RADIUS)
				clickRadiusAbsolute = clickRadius / scale  # click radius
				bubbles = layer.tempData[TempDataBubblesKey]
				nodesL, nodesR = bubbles[TempDataLeftNodesKey], bubbles[TempDataRightNodesKey]
				allNodes = nodesL + nodesR

				hit_index = None
				for i, node in enumerate(allNodes):  # find the possibly selected node. Escape as soon as it finds one
					if nearNodes(node.pos, clickPosition, clickRadiusAbsolute):
						hit_index = i
						break

				if hit_index is None and self.closestNode:  # clicked a node

					nodeAdded = False
					# GET THE CLOSEST POINTS TO THE CLICKED POSITION
					closestL = closestToNodes(nodesL, clickPosition)  # TWO COORDINATE NUMBERS, NOT .X AND .Y
					closestR = closestToNodes(nodesR, clickPosition)
					if closestL is None or closestR is None:
						return
					# EVALUATE WHICH BUBBLE IS WITHIN CLICKED POSITION AND WHICH IS CLOSER
					closestDeltaL = hypot(cpx - closestL[0], cpy - closestL[1])
					closestDeltaR = hypot(cpx - closestR[0], cpy - closestR[1])
					if closestDeltaL <= clickRadiusAbsolute:  # IF closestL IS SELECTABLE
						if closestDeltaL <= closestDeltaR:  # nodesL IS CLOSER, R MAY BE IN OR OUT
							nodes = nodesL
							closest = closestL
							sideName = TempDataLeftNodesKey
							nodeAdded = True
						else:  # R IS MORE SELECTABLE (WHEN BOTH SHOULD BE SELECTABLE)
							nodes = nodesR
							closest = closestR
							sideName = TempDataRightNodesKey
							nodeAdded = True
					elif closestDeltaR <= clickRadiusAbsolute:  # IF ONLY closestR IS SELECTABLE
						nodes = nodesR
						closest = closestR
						sideName = TempDataRightNodesKey
						nodeAdded = True

					# CHECK IF THE CLOSEST NODE IS WITHIN CLICKABLE RADIUS
					# IF CLOSE ENOUGH, THAT'S A NEW NODE
					if nodeAdded is True:
						newX = tempToUserNodeX(closest[0], closest[1], m.italicAngle, m.xHeight)  # correct for italic angle
						new_node = makeBubbleNode(newX, closest[1], m.italicAngle, m.xHeight)

						# INSERT AT CORRECT POS, NOT AT THE LAST INDEX
						nodes.append(new_node)

						bubbles[sideName] = sorted(nodes, key=lambda n: n.pos.y)
						self.saveNodesToLayer(layer)

						layer.selection = [new_node]
						controller.redraw()
						return
			objc.super(BubbleKernTool, self).mouseDown_(theEvent)

		except:
			print("mouseDown_ error: " + traceback.format_exc())


	def insertTab_(self, sender):  # WHEN TAB IS PRESSED
		self._selectNext(1)

	def insertBacktab_(self, sender):  # WHEN SHIFT+TAB IS PRESSED
		self._selectNext(-1)

	@objc.python_method
	def _selectNext(self, direction):  # CYCLE THROUGH SELECTED NODE WITH TAB
		layer = self.activeLayer
		bubbles = layer.tempData[TempDataBubblesKey]
		allNodes = bubbles.get(TempDataLeftNodesKey, []) + bubbles.get(TempDataRightNodesKey, [])

		selection = [n for n in layer.selection if isinstance(n, BubbleNode)]
		if len(selection) == 0:
			# selection = [allNodes[0]]
			return
		index = allNodes.index(selection[0])
		nextNode = allNodes[(index + direction) % len(allNodes)]
		layer.selection = [nextNode]

	@objc.python_method
	def validateReferGlyph(self, layer, side):  # CALLED FROM SelectAll. SIDE IS EITHER 'L' OR 'R'
		try:
			mId = layer.associatedMasterId
			if not self.activeLayer.userData['BubbleKernRefer' + side]:  # IF INHERIT ENTRY DOESN'T EXIST
				return False

			gName = self.activeLayer.userData['BubbleKernRefer' + side]
			font = layer.font
			if not font.glyphs[gName]:  # REFERRED GLYPH NAME IS INVALID
				return False

			referredLayer = font.glyphs[gName].layers[mId]
			if 'BubbleKernRefer' + side not in referredLayer.userData:  # CHECK NESTED INHERITANCE
				return False  # REFERRED GLYPH HAS NO BUBBLEKERN USERDATA IN THE LAYER

			if referredLayer.userData['BubbleKernRefer' + side] != '':  # NEST CONFIRMED
				if self.validateReferGlyph(referredLayer, side):
					return True
				else:
					return False

			elif 'BubbleKernNodes' + side in referredLayer.userData:  # ASSUMED SAFE AT THIS POINT
				return True

		except:
			traceback.print_exc()

	# CALLED WHEN SELECT ALL HAS BEEN CALLED FROM THE APP
	def selectAll_(self, sender):
		try:
			self.setActiveLayer()

			if self.activeLayer.name is None:
				return
			if self.activeLayer.isAligned:
				return

			# layer.selection = [] # Reset selection

			bubbles = self.activeLayer.tempData[TempDataBubblesKey]
			nodesToAdd = []
			# print('0 bubbles', layer, bubbles)
			for n in (bubbles.get(TempDataLeftNodesKey, []) + bubbles.get(TempDataRightNodesKey, [])):
				n.selected = False
			
			for side in (TempDataLeftNodesKey, TempDataRightNodesKey):
				# SKIP IF INHERITING A (VALID) GLYPH
				if side == TempDataLeftNodesKey and self.validateReferGlyph(self.activeLayer, 'L') == False:
					nodesToAdd.extend(bubbles.get(side, []))
				if side == TempDataRightNodesKey and self.validateReferGlyph(self.activeLayer, 'R') == False:
					nodesToAdd.extend(bubbles.get(side, []))

			# print('2 nodesToAdd', layer, nodesToAdd)

			# for n in nodesToAdd:
			# 	n.selected = True
			self.activeLayer.selection = nodesToAdd

			Glyphs.redraw()
		except:
			print(traceback.print_exc())

	def alignPoints_(self, sender):
		alignment = alignment = Glyphs.defaults["GSTransformGridCorner"]
		# GSTopLeft = 6,
		# GSTopCenter = 7,
		# GSTopRight = 8,
		# GSCenterLeft = 3,
		# GSCenterCenter = 4,
		# GSCenterRight = 5,
		# GSBottomLeft = 0,
		# GSBottomCenter = 1,
		# GSBottomRight = 2,
		layer = self.activeLayer
		# get selection size

		bubbles = layer.tempData[TempDataBubblesKey]

		allNodes = bubbles.get(TempDataLeftNodesKey, []) + bubbles.get(TempDataRightNodesKey, [])

		selectedNodes = [n for n in allNodes if n in layer.selection]

		if len(selectedNodes) > 1:  # if there are 2 or more nodes selected

			xCoords = [n.pos.x for n in selectedNodes]
			xMin, xMax = min(xCoords), max(xCoords)

			yCoords = [n.pos.y for n in selectedNodes]
			yMin, yMax = min(yCoords), max(yCoords)

			if xMax - xMin < yMax - yMin:  # TALLER SELECTION BOX; FLATTEN X VALUES
				if alignment in (0, 3, 6):   # X MININUM
					alignX = int(round(xMin))
				elif alignment in (1, 4, 7):  # X CENTRE
					alignX = int(round(xMin + (xMax - xMin) / 2))
				else:                      # X MAX
					alignX = int(round(xMax))
				for n in selectedNodes:
					n.pos = NSPoint(alignX, n.pos.y)
			else:                     # WIDER SELECTION BOX; FLATTEN Y VALUES
				if alignment in (0, 1, 1):   # Y MINIMUM
					alignY = int(round(yMin))
				elif alignment in (3, 4, 5):  # Y CENTRE
					alignY = int(round(yMin + (yMax - yMin) / 2))
				else:                      # Y MAX
					alignY = int(round(yMax))
				for n in selectedNodes:
					n.pos = NSPoint(n.pos.x, alignY)
			self.saveNodesToLayer(layer)
			Glyphs.redraw()

	def delSelectionWithModifier_(self, modifierFlag):  # Called when Delete is pressed
		controller = self.editViewController()
		layer = controller.activeLayer()
		if layer and layer.selection:
			bubbles = layer.tempData[TempDataBubblesKey]
			if not bubbles:
				return
			for selection in layer.selection:
				nodeL = bubbles[TempDataLeftNodesKey]
				nodeR = bubbles[TempDataRightNodesKey]
				if selection in nodeL:
					nodeL.remove(selection)
				if selection in nodeR:
					nodeR.remove(selection)
			self.saveNodesToLayer(layer)
			controller.redraw()

	@objc.python_method
	def eraseBubble(self, sender):  # CALLED FROM INFO BOX; REMOVES BUBBLE FROM A LAYER. MOVE TO COMMON LOGIC?
		try:
			ud = self.activeLayer.userData
			if sender == self.w.group.menusL:
				bubbleKeys = ('BubbleKernReferL', 'BubbleKernExportL', 'BubbleKernNodesL')
			else:
				bubbleKeys = ('BubbleKernReferR', 'BubbleKernExportR', 'BubbleKernNodesR')
			for key in bubbleKeys:
				del ud[key]
		except:
			pass

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
