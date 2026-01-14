# THE TOOL BASED ON SELECTTOOL FOR EDITING BUBBLES.

import objc
from objc import super
import traceback
from math import hypot, radians, tan
import vanilla
from GlyphsApp import Glyphs, UPDATEINTERFACE
from GlyphsApp.plugins import SelectTool
from Cocoa import (
	NSAffineTransform,
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
	NSShiftKeyMask, NSCommandKeyMask, NSAlternateKeyMask,  # for doing stuff in mouseDown_() and keyDown_()
	NSAlert,
	NSAlertStyleCritical,
)


# from BKReporter import ShowKernBubbles4

DEBUG_COORDS = True  # set to False to reduce logging

# constants
fontSize = 12
clickRadius = 8

# UI STUFF FOR DISPLAYING INFO BOX
# Patched Vanilla Group class to generate Info Box
GSInspectorView = objc.lookUpClass("GSInspectorView")
class InspectorGroup(vanilla.Group):
	nsViewClass = GSInspectorView

# UI STUFF FOR SHOWING DIALOG
# May come in handy

def show_alert(message: str, secondMessage: str = ''):
	alert = NSAlert.alloc().init()
	alert.setMessageText_(message)
	if secondMessage != '':
		alert.setInformativeText_(secondMessage)
	alert.addButtonWithTitle_("OK")  # index 1000
	alert.addButtonWithTitle_("Cancel")  # index 1001
	alert.setAlertStyle_(NSAlertStyleCritical)
	response = alert.runModal()
	if response == 1000:  # OK
		return True
	elif response == 1001:  # Cancel
		return False


class BubbleNode(object):
	x: float = 0
	y: float = 0
	# position: NSPoint = NSPoint(0, 0)

	def __init__(self, x, y, angle, xHeight):
		if angle != 0:
			angle = radians(90 - angle)
			newX = x - (y - xHeight / 2) / tan(angle)
		else:
			newX = x
		self.x = int(round(newX))
		self.y = int(round(y))
		self.selected = False

	def __repr__(self):
		return f"(BubbleNode x={self.x}, y={self.y}, selected={self.selected})"

# def handleAtPosition(position):
# 	handle = BubbleNode.new()
# 	handle.setPosition_(position)
# 	return handle

def closest_point_on_segment(A, B, P):  # A=node0, B=node1, P=clicked point
	x1, y1 = A.x, A.y
	x2, y2 = B.x, B.y
	x0, y0 = P.x, P.y
	dx = x2 - x1  # s distance
	dy = y2 - y1  # y disance

	if dx == 0 and dy == 0:  # A and B are the same point
		return A.x, A.y
	# Projection parameter t
	t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
	# Clamp to segment
	t = max(0, min(1, t))
	# Closest point
	closest_x = x1 + t * dx
	closest_y = y1 + t * dy

	return closest_x, closest_y

# compares if node0 and node1 are close enough, i.e. distance is within threshold
def nearNodes(node0, node1, threshold):
	dx = node1.x - node0.x
	dy = node1.y - node0.y
	if (dx * dx + dy * dy) <= (threshold * threshold):
		return True
	else:
		return False

# checks if mousePos is on the series of segments made by 'nodes'.
# Assumes 'nodes' starts from bottom
def closestToNodes(nodes, mousePos):
	if nodes[-1].y < mousePos.y:  # if cursor is too far above the bubble
		return nodes[-1].x, nodes[-1].y
	elif nodes[0].y > mousePos.y:  # if too far below the bubble
		return nodes[0].x, nodes[0].y
	else:
		for i, n in enumerate(nodes):
			if n != nodes[-1]:
				if n.y <= mousePos.y <= nodes[i + 1].y:  # mousePos Y is between these two nodes
					return closest_point_on_segment(n, nodes[i + 1], mousePos)
	return None

def italicOffset(node, angle, xHeight):  # FOR DISPLAYING ITALIC-ADJUSTED COORDFINATES
	try:
		angle = radians(90 - angle)
		newX = node.x - (node.y - xHeight / 2) / tan(angle)
		return newX
	except:
		return 0

class BubbleKernTool4(SelectTool):

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize(
			{
				"en": "BubbleKern 4",
			}
		)
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
		self.keyboardShortcutModifier = (NSCommandKeyMask | NSShiftKeyMask | NSAlternateKeyMask)
		self.keyboardShortcut = 'b'
		self.toolbarPosition = 13
		self.font = None
		self.bubbles = {}
		self.layerOfExtraHandles = None
		self.isCreateAction = False
		self.horizontal = getattr(self, "horizontal", True)  # whether horizontal or vertical bubbles
		self.closestNode = None  # for highlighting the addable node
		self.selectableNode = None  # for highlighting the selectable node
		# imported from copilot code
		self._mouseDownPos = getattr(self, "_mouseDownPos", (0.0, 0.0))  # to track the start of mouse down when dragging
		self._dragging = getattr(self, "_dragging", False)  # boolean whether bing moved
		self._dragging_nodes = getattr(self, "_dragging_nodes", [])  # node being moved (convert to plural?)
		self._drag_offset = getattr(self, "_drag_offset", (0.0, 0.0))  # dragging box

		self.w = vanilla.Window((360, 10))

		self.w.group = InspectorGroup("auto")
		self.w.group.glyphNameL = vanilla.EditText('auto', '', callback=self.infoBox, placeholder='Copy glyph')
		self.w.group.line = vanilla.VerticalLine('auto')
		self.w.group.glyphNameR = vanilla.EditText('auto', '', callback=self.infoBox, placeholder='Copy glyph')
		menuItems = [
			dict(title='Auto-Generate Bubble', callback=None),
			dict(title='Decompose Inherited', callback=None),
			dict(title='Reset Bubble', callback=None),
			dict(title='Erase Bubble', callback=self.eraseBubble),
			dict(title='Show Compatibility', callback=None),
			dict(title='Show Node Coordinates', callback=None)
		]
		self.w.group.exportL = vanilla.CheckBox('auto', 'Export', callback=None)
		self.w.group.exportR = vanilla.CheckBox('auto', 'Export', callback=None)
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

	@objc.python_method
	def start(self):  # when app starts.
		pass

	@objc.python_method
	def activate(self):  # when the tool is activated
		self.active = True
		try:
			print('activate called')
			Glyphs.addCallback(self.updateUI, UPDATEINTERFACE)
			self.font = Glyphs.font
			m = self.font.selectedFontMaster
			self.activeLayer = self.font.currentTab.graphicView().activeLayer()
			self.layerWidthPrev = self.activeLayer.width  # to keep track of width change for correcting R bubble
			self.loadNodesFromLayer(self.activeLayer)
		except:
			print(traceback.print_exc())

	@objc.python_method
	def deactivate(self):  # when the tool is deactivated / went to font view
		self.active = False
		self.bubbles = {}
		Glyphs.removeCallback(self.updateUI, UPDATEINTERFACE)
		# self.bkToolWindow.w.close()
		pass

	# They should enable drawing default path in inactive and active layers.
	# NOT WORKING. Glyphs doesn't seem to handle the return value.
	@objc.python_method
	def needsExtraMainOutlineDrawingForInactiveLayer_(self, layer, info=None):
		# ignore if it's not the starting font
		if layer.parent.parent != self.font:
			return
		return True

	@objc.python_method
	def needsExtraMainOutlineDrawingForActiveLayer_(self, layer, info=None):
		# ignore if it's not the starting font
		if layer.parent.parent != self.font:
			return
		return True

	@objc.python_method
	def infoBox(self, sender):  # CALLED IF INFO BOX UI ELEMENTS ARE EDITED
		try:
			self.activeLayer.userData['BubbleKernInheritL'] = self.w.group.glyphNameL.get()
			self.activeLayer.userData['BubbleKernInheritR'] = self.w.group.glyphNameR.get()
			self.activeLayer.userData['BubbleKernExportL'] = self.w.group.exportL.get()
			self.activeLayer.userData['BubbleKernExportR'] = self.w.group.exportR.get()
			Glyphs.redraw()
		except:
			print('infoBox error', traceback.print_exc())

	@objc.python_method
	def updateUI(self, theEvent):  # CALLED IF ANYTHING IN THE WINDOW CHANGES
		try:
			print('updateUI called', theEvent)
			self.loadNodesFromLayer()
			if self.layerWidthPrev != self.activeLayer.width:  # RSB OR WIDTH HAS CHANGED
				self.layerWidthPrev = self.activeLayer.width
				# Glyphs.redraw()

			self.w.group.glyphNameL.set(self.activeLayer.userData['BubbleKernInheritL'])
			self.w.group.glyphNameR.set(self.activeLayer.userData['BubbleKernInheritR'])
			self.w.group.exportL.set(bool(self.activeLayer.userData['BubbleKernExportL']))
			self.w.group.exportR.set(bool(self.activeLayer.userData['BubbleKernExportR']))
		except:
			print('updateUI error', traceback.print_exc())

	def view(self):  # SHOWS INFO BOX; CALLED CONSTANTLY
		# RETURN NONE WHEN YOU WANT TO DISABLE INFO BOX
		return self.infoBoxView

	@objc.python_method
	def saveNodesToLayer(self):
		layer = self.activeLayer
		# layer.userData['BubbleKernExportL'] = self.bubbles['exportL']
		# layer.userData['BubbleKernExportR'] = self.bubbles['exportR']
		# layer.userData['BubbleKernInheritL'] = self.w.group.glyphNameL.get()
		# layer.userData['BubbleKernInheritR'] = self.w.group.glyphNameR.get()

		self.activeLayer.userData['BubbleKernInheritL'] = self.w.group.glyphNameL.get()
		self.activeLayer.userData['BubbleKernInheritR'] = self.w.group.glyphNameR.get()
		self.activeLayer.userData['BubbleKernExportL'] = int(self.w.group.exportL.get())
		self.activeLayer.userData['BubbleKernExportR'] = int(self.w.group.exportR.get())

		layer.userData['BubbleKernNodesL'] = [[int(n.x), int(n.y)] for n in self.bubbles['nodesL']]
		# RIGHT SIDE SHOULD ALWAYS BE BASED ON RSB. WHAT ABOUT ITALICS ?
		layer.userData['BubbleKernNodesR'] = [[int(n.x - layer.width), int(n.y)] for n in self.bubbles['nodesR']]

	# LOAD BUBBLE FROM LAYER'S USERDATA. CHECKS MAY BE TOO STRICT THOUGH.
	@objc.python_method
	def loadNodesFromLayer(self, layer=None, forceLoad=True):
		try:
			# print('loadNodesFromLayer commenced')
			if layer is None:
				# print(self.font)
				# print(self.font.currentTab)
				# print(self.font.currentTab.graphicView())
				layer = self.font.currentTab.graphicView().activeLayer()
			self.activeLayer = layer
			m = self.font.selectedFontMaster
			self.bubbles = {}
			attributes = ('BubbleKernExportL', 'BubbleKernInheritL', 'BubbleKernNodesL', 'BubbleKernExportR', 'BubbleKernInheritR', 'BubbleKernNodesR')
			if False in [a in layer.userData for a in attributes]:
				# IN ANY KEY IS MISSING, MAYBE LOAD DEFAULT
				if forceLoad is True:
					# m = self.font.selectedFontMaster
					self.bubbles = {
						# 'exportL' : True,
						# 'exportR' : True,
						# 'inheritL' : '',
						# 'inheritR' : '',
						'nodesL': [BubbleNode(0, m.descender, m.italicAngle, m.xHeight), BubbleNode(0, m.ascender, m.italicAngle, m.xHeight)],
						'nodesR': [BubbleNode(layer.width, m.descender, m.italicAngle, m.xHeight), BubbleNode(layer.width, m.ascender, m.italicAngle, m.xHeight)],
						# 'nodesBeforeDragL': [],
						# 'nodesBeforeDragR': [],
					}
					self.w.group.glyphNameL.set('')
					self.w.group.glyphNameR.set('')
					self.w.group.exportL.set(True)
					self.w.group.exportR.set(True)
					self.saveNodesToLayer()
					print('loadNodesFromLayer: Default Bubble made!', layer.parent.name)
				else:  # I DON'T WANT TO FORCE LOAD. MAINLY USED IN INACTIVE LAYER DRAWING
					self.bubbles = {}  # THE ACTUAL DEFAULTING PART
					print('loadNodesFromLayer: Layer loading skipped!', layer.parent.name)
			else:
				# LOAD EXISTING

				# self.bubbles['exportL'] = bool(layer.userData['BubbleKernExportL'])
				# self.bubbles['exportR'] = bool(layer.userData['BubbleKernExportR'])
				# self.bubbles['inheritL'] = layer.userData['BubbleKernInheritL']
				# self.bubbles['inheritR'] = layer.userData['BubbleKernInheritR']

				self.w.group.glyphNameL.set(self.activeLayer.userData['BubbleKernInheritL'])
				self.w.group.glyphNameR.set(self.activeLayer.userData['BubbleKernInheritR'])
				self.w.group.exportL.set(bool(self.activeLayer.userData['BubbleKernExportL']))
				self.w.group.exportR.set(bool(self.activeLayer.userData['BubbleKernExportR']))

				self.bubbles['nodesL'] = [BubbleNode(n[0], n[1], m.italicAngle, m.xHeight) for n in layer.userData['BubbleKernNodesL']]
				# nodesR'S X VALUES ARE BASED ON LAYER WIDTH WHEN SAVED
				# IN self.bubbles TEMP DATA, THEY ARE ACTUAL VALUES
				self.bubbles['nodesR'] = [BubbleNode(n[0] + layer.width, n[1], m.italicAngle, m.xHeight) for n in layer.userData['BubbleKernNodesR']]
				# self.bubbles['nodesBeforeDragL'] = []
				# self.bubbles['nodesBeforeDragR'] = []
				print('loadNodesFromLayer: Existing Bubble loaded!', layer.parent.name)
			Glyphs.redraw()
			return True
		except:
			print('bubble load failed')
			print(traceback.print_exc())
			return False

	def updateExtraHandles(self):
		graphicView = self.editViewController().graphicView()
		if layer := graphicView.activeLayer():
			if self.layerOfExtraHandles != layer:
				self.layerOfExtraHandles = layer
				if info := layer.userData["SampleInfo"]:
					self.setExtraHandles_(
						[handleAtPosition(NSPoint(x, y)) for [x, y] in info]
					)
				else:
					self.setExtraHandles_([])

	@objc.python_method
	def updateLayerSampleInfo(self, layer):
		extraHandles = self.extraHandles() or []
		layer.userData["SampleInfo"] = [
			[h.position.x, h.position.y]
			for h in extraHandles
			if isinstance(h, BubbleNode)
		]

	def deselectNodes(self):
		try:
			for n in self.bubbles['nodesL'] + self.bubbles['nodesR']:
				n.selected = False
		except:
			print(traceback.print_exc())

	@objc.python_method
	def drawLayer_(self, layer, layerOrigin, asActive, attributes=None):
		print('hello', layer)
	#drawLayer:(GSLayer *)layer atPoint:(NSPoint)layerOrigin asActive:(BOOL)active attributes:(NSDictionary *)attributes;

	@objc.python_method
	def foreground(self, layer):


		# layer to draw nodes
		# if Glyphs.isActive() is False: # SKIP DRAWING IF GLYPHS IS NOT IN FRONT. REALLY NECESSARY?
		# 	return
		try:
			graphicView = self.editViewController().graphicView()
			scale = graphicView.scale()
			halo_margin = 3 / scale  # size of selection marker
			diameter = 10 / scale  # size of node
			radius = diameter / 2
			italicAngle = layer.associatedFontMaster().italicAngle
			xHeight = layer.associatedFontMaster().xHeight

			if layer != self.activeLayer:  # IF DIFFERENT FROM PREVIOUSLY KNOWN LAYER
				print('loading from foreground()')
				self.loadNodesFromLayer(layer)


			# ONLY DRAW THESE WHEN NOT AUTO-INHERITED AND COMPONENTS ARE NOT ALIGNED
			drawNodesL = self.activeLayer.userData['BubbleKernInheritL'] == '' and self.activeLayer.isAligned is False
			drawNodesR = self.activeLayer.userData['BubbleKernInheritR'] == '' and self.activeLayer.isAligned is False

			nodesL = self.bubbles['nodesL']
			nodesR = self.bubbles['nodesR']
			allNodes = nodesL + nodesR

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
					rect = NSMakeRect(n.x - radius, n.y - radius, diameter, diameter)
					path = NSBezierPath.bezierPathWithOvalInRect_(rect)
					path.setLineWidth_(2 / scale)
					path.stroke()


			# HIGHLIGHT SELECTION
			if layer == self.activeLayer:
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
						if n.selected:
							rect = NSMakeRect(n.x - radius, n.y - radius, diameter, diameter)
							path = NSBezierPath.bezierPathWithOvalInRect_(rect)
							path.fill()

				# DISPLAY COORDINATES WHEN SELECTED
				fontAttributes = {
					#NSFontAttributeName: NSFont.labelFontOfSize_(10.0),
					NSFontAttributeName: NSFont.monospacedDigitSystemFontOfSize_weight_(fontSize / scale, 0.0),
					NSForegroundColorAttributeName: NSColor.textColor()
				}
				for n in nodesL + nodesR:
					if n.selected:
						if n in nodesL:
							realX = italicOffset(n, italicAngle, xHeight) if italicAngle != 0 else n.x
							coordinates = f'{int(round(realX))}, {int(round(n.y))}'
						else:
							realX = italicOffset(n, italicAngle, xHeight) if italicAngle != 0 else n.x
							coordinates = f'{int(round(realX - self.activeLayer.width))}, {int(round(n.y))}'
						# coordinates = italicOffset(n, italicAngle, xHeight)
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
			if self.selectableNode is not None or self.closestNode is not None:

				# color = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
				# color.set()
				if self.selectableNode is not None:  # if mouseMoved_() says there's a selectable node
					n = self.selectableNode
					if n.selected is False:  # if the node is not selected yet
						if n in nodesL:
							color = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
						else:
							color = NSColor.systemPinkColor().colorWithAlphaComponent_(0.5)
						color.set()
						rect = NSMakeRect(n.x - radius, n.y - radius, diameter, diameter)
						path = NSBezierPath.bezierPathWithOvalInRect_(rect)
						path.fill()
				elif self.closestNode is not None:  # if mouseMoved_() says there's a add-able node on a line
					color = NSColor.systemGrayColor().colorWithAlphaComponent_(0.75)
					color.set()
					n = self.closestNode
					rect = NSMakeRect(n[0] - radius, n[1] - radius, diameter, diameter)
					path = NSBezierPath.bezierPathWithOvalInRect_(rect)
					path.setLineWidth_(1 / scale)
					path.stroke()


			# HIGHLIGHT DRAG BOX
			if self._dragging and self._dragging_nodes == []:
				originX, originY = self._mouseDownPos[0], self._mouseDownPos[1]
				dx, dy = self._drag_offset
				rect = NSMakeRect(originX, originY, dx, dy)
				path = NSBezierPath.bezierPathWithRect_(rect)
				color = NSColor.systemGrayColor().colorWithAlphaComponent_(0.1)
				color.set()
				path.fill()
		except:
			print(traceback.print_exc())

	@objc.python_method
	def background(self, layer):
		# LAYER TO DRAW GRID AND BUBBLE
		if Glyphs.isActive() is False:  # DISABLE DRAWING WHILE IN BACKGROUND
			return
		try:
			# "TRUE" REFERS TO ACTIVE STATE
			self.drawBubbleWalls(layer, True, self.font.currentTab.selectedLayerOrigin, {})

		# 	f = self.font
		# 	mId = layer.associatedMasterId
		# 	scale = f.currentTab.scale
		# 	originY = f.currentTab.selectedLayerOrigin.y

		# 	if layer.isAligned: # DRAW PRE-COMPOSED BUBBLES
		# 		pass
		# 	else:
		# 		if layer != self.activeLayer: # IF DIFFERENT FROM PREVIOUSLY KNOWN LAYER
		# 			print('loading from background()')
		# 			self.loadNodesFromLayer(layer)

		# 		# bubbleL, bubbleR = layer.userData['BubbleKernNodesL'], layer.userData['BubbleKernNodesR']
		# 		for side in ('nodesL', 'nodesR'):
		# 			if side == 'nodesL':
		# 				color = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
		# 			else:
		# 				color = NSColor.systemPinkColor().colorWithAlphaComponent_(0.5)
		# 			color.set()

		# 			nodes = []
		# 			if side == 'nodesL' and layer.userData['BubbleKernInheritL']:
		# 				# IMPORT LEFT NODES FROM REFERRED NODE
		# 				try:
		# 					sourceLayer = f.glyphs[layer.userData['BubbleKernInheritL']].layers[mId]
		# 					if 'BubbleKernNodesL' in sourceLayer.userData:
		# 						nodes = [NSPoint(n[0], n[1]) for n in sourceLayer.userData['BubbleKernNodesL']]
		# 				except:
		# 					pass
		# 					# print(traceback.format_exc())
		# 			elif side == 'nodesR' and layer.userData['BubbleKernInheritR']:
		# 				# IMPORT RIGHT NODES FROM REFERRED NODE
		# 				try:
		# 					sourceLayer = f.glyphs[layer.userData['BubbleKernInheritR']].layers[mId]
		# 					if 'BubbleKernNodesR' in sourceLayer.userData:
		# 						nodes = [NSPoint(n[0]+layer.width, n[1]) for n in sourceLayer.userData['BubbleKernNodesR']]
		# 				except:
		# 					pass
		# 			else: # DRAW BUBBLE AS NORMAL
		# 				nodes = self.bubbles[side]
		# 			# print(side, nodes)

		# 			if nodes:
		# 				bubblePath = NSBezierPath.alloc().init()
		# 				for i, n in enumerate(nodes):
		# 					if i == 0: # if first node
		# 						bubblePath.moveToPoint_(NSPoint(n.x, n.y))
		# 					else:
		# 						bubblePath.lineToPoint_(NSPoint(n.x, n.y))
		# 				bubblePath.setLineWidth_(2/scale)
		# 				bubblePath.stroke()

		except Exception:
			print("background error: " + traceback.format_exc())

	# INACTIVE LAYERS. WORKS, BUT I NEED TO IMPLEMENT REUSABLE/INHERITED SHAPE DRAWING
	def drawLayer_atPoint_asActive_attributes_(self, layer, layerOrigin, active, layerAttributes):
		try:
			if active:
				return
			self.drawBubbleWalls(layer, active, layerOrigin, layerAttributes)
			# NSColor.redColor().set() # Example: draw a rectangle at the layer origin
			# rect = NSMakeRect(layerOrigin.x, layerOrigin.y, 100, 100)
			# path = NSBezierPath.bezierPathWithRect_(rect)
			# path.stroke()
		except:
			print("drawLayer_atPoint_asActive_attributes_ error: " + traceback.format_exc())

	@objc.python_method
	def drawBubbleWalls(self, layer, active, layerOrigin, layerAttributes):
		try:
			f = self.font
			mId = layer.associatedMasterId
			scale = f.currentTab.scale

			if layer.isAligned:  # DRAW PRE-COMPOSED BUBBLES
				pass
			else:
				if active is False:  # PREPARE TRANSFORM FOR INACTIVE LAYERS
					inactiveTransform = NSAffineTransform.transform()
					inactiveTransform.translateXBy_yBy_(layerOrigin.x, layerOrigin.y)
					inactiveTransform.scaleXBy_yBy_(scale, scale)

				if active and layer != self.activeLayer:  # IF DIFFERENT FROM PREVIOUSLY KNOWN LAYER
					# NECESSARY TO KEEP TRACK OF SHAPE WHILE DRAGGING IN ACTIVE LAYER
					self.loadNodesFromLayer(layer, forceLoad=active)


				# DEFAULT LAYER CONTENT DRAWING ATTEMPT 1
				# layerOrigin = (0,0) if layerOrigin == None else layerOrigin
				# print(layer, active, layerOrigin, layerAttributes)
				# super().drawLayer_atPoint_asActive_attributes_(layer, layerOrigin, active, layerAttributes)

				# DEFAULT LAYER CONTENT DRAWING ATTEMPT 2. I WANT TO REMOVE IT ONCE I FIGURE OUT HOW TO DO IT BY DEFAULT.
				layerBP = layer.completeBezierPath
				if active is False:
					layerBP.transformUsingAffineTransform_(inactiveTransform)
				NSColor.textColor().set()
				layerBP.fill()

				# bubbleL, bubbleR = layer.userData['BubbleKernNodesL'], layer.userData['BubbleKernNodesR']
				for side in ('nodesL', 'nodesR'):
					if side == 'nodesL':
						color = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
					else:
						color = NSColor.systemPinkColor().colorWithAlphaComponent_(0.5)
					color.set()

					nodes = []
					if side == 'nodesL' and layer.userData['BubbleKernInheritL']:
						# IMPORT LEFT NODES FROM REFERRED NODE
						try:
							sourceLayer = f.glyphs[layer.userData['BubbleKernInheritL']].layers[mId]
							if 'BubbleKernNodesL' in sourceLayer.userData:
								nodes = [NSPoint(n[0], n[1]) for n in sourceLayer.userData['BubbleKernNodesL']]
						except:
							pass
					elif side == 'nodesR' and layer.userData['BubbleKernInheritR']:
						# IMPORT RIGHT NODES FROM REFERRED NODE
						try:
							sourceLayer = f.glyphs[layer.userData['BubbleKernInheritR']].layers[mId]
							if 'BubbleKernNodesR' in sourceLayer.userData:
								nodes = [NSPoint(n[0] + layer.width, n[1]) for n in sourceLayer.userData['BubbleKernNodesR']]
						except:
							pass
					else:  # USE ITS OWN BUBBLE DATA, NOT USING REFERRED GLYPHS
						if active is False:  # IF INACTIVE, LOAD FROM LAYER.USERDATA
							sideName = 'BubbleKernNodesL' if side == 'nodesL' else 'BubbleKernNodesR'
							if sideName in layer.userData:  # IF USERDATA EXISTS
								nodes = layer.userData[sideName]
								if sideName == 'BubbleKernNodesL':
									nodes = [NSPoint(n[0], n[1]) for n in nodes]
								else:
									nodes = [NSPoint(n[0] + layer.width, n[1]) for n in nodes]
						elif side in self.bubbles:  # BETTER TO CHECK JUST IN CASE
							nodes = self.bubbles[side]

					if nodes:
						bubblePath = NSBezierPath.alloc().init()
						for i, n in enumerate(nodes):
							if i == 0:  # if first node
								bubblePath.moveToPoint_(NSPoint(n.x, n.y))
							else:
								bubblePath.lineToPoint_(NSPoint(n.x, n.y))
						if active is True:  # WHEN IN BACKGROUND
							bubblePath.setLineWidth_(2 / scale)
						else:
							bubblePath.transformUsingAffineTransform_(inactiveTransform)
							bubblePath.setLineWidth_(2)

						bubblePath.stroke()

		except Exception:
			print("drawBubbleWalls error: " + traceback.format_exc())

	def elementAtPoint_atLayer_ignoreLocked_(self, point, layer, ignoreLocked):
		scale = self.editViewController().graphicView().scale()
		tolerance = 7 / scale
		if extraHandles := self.extraHandles():
			for handle in extraHandles:
				if isinstance(handle, BubbleNode):
					handlePosition = handle.position
					if (
						hypot(point.x - handlePosition.x, point.y - handlePosition.y)
						< tolerance
					):
						return handle
		return None


	def mouseMoved_(self, theEvent):
		try:
			graphicView = self.editViewController().graphicView()
			f = self.font
			scale = f.currentTab.scale
			mousePos = graphicView.getActiveLocation_(theEvent)  # pos relative to active layer
			mpx, mpy = mousePos.x, mousePos.y
			clickRadiusAbsolute = clickRadius / scale  # click radius
			# highlight possible click position
			# highlight possible selectable node
			nodesL, nodesR = self.bubbles['nodesL'], self.bubbles['nodesR']
			allNodes = nodesL + nodesR

			# highlight clickable node
			for n in allNodes:
				if nearNodes(n, mousePos, clickRadiusAbsolute):
					self.selectableNode = n  # for highlighting the selectable node
					Glyphs.redraw()
					return
			self.selectableNode = None

			# highlight possible node add position
			closestL = closestToNodes(nodesL, mousePos)  # two coordinate numbers, not .x and .y
			closestR = closestToNodes(nodesR, mousePos)
			closestDeltaL = hypot(mpx - closestL[0], mpy - closestL[1])
			closestDeltaR = hypot(mpx - closestR[0], mpy - closestR[1])
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
			if closest != None:
				self.closestNode = closest  # for highlighting the addable node
				Glyphs.redraw()
			elif self.closestNode != None:  # closest is None but self.closest is present, need to de-select
				self.closestNode = None
				Glyphs.redraw()

		except:
			pass
			# It throws error when not in Glyphs, not worth paying attention
			# print("mouseMoved_ error: " + traceback.format_exc())

	def mouseDown_(self, theEvent):
		try:
			if theEvent.clickCount() > 1:
				super().mouseDown_(theEvent)
				return

			controller = self.editViewController()
			graphicView = controller.graphicView()

			if layer := graphicView.activeLayer():
				m = layer.associatedFontMaster()
				scale = graphicView.scale()
				self._mouseDownPos = graphicView.getActiveLocation_(theEvent)
				clickPosition = graphicView.getActiveLocation_(theEvent)
				cpx, cpy = clickPosition.x, clickPosition.y

				# if DEBUG_COORDS:
				# 	print(f"mouseDown_: computed layer_pt=({cpx:.2f},{cpy:.2f})")

				# hit_radius_layer = self._pixel_radius_to_layer(HIT_PIXEL_RADIUS)
				clickRadiusAbsolute = clickRadius / scale  # click radius

				nodesL, nodesR = self.bubbles['nodesL'], self.bubbles['nodesR']
				allNodes = nodesL + nodesR

				hit_index = None
				for i, node in enumerate(allNodes):  # find the possibly selected node. Escape as soon as it finds one
					if nearNodes(node, clickPosition, clickRadiusAbsolute):
						hit_index = i
						break

				if hit_index is not None:  # clicked a node
					node = allNodes[hit_index]  # the clicked node
					if theEvent.modifierFlags() == 131074:  # if shift is being pressed. Different from keyDown_
						# the shift detection is not working
						node.selected = not node.selected  # toggle selection
					else:  # click or start of dragging, impossible to know yet
						if node.selected is False:  # this should be the only selected node
							self.deselectNodes()
						node.selected = True
						self._dragging = True
						# self._dragging_nodes = [hit_index]
						self._dragging_nodes = [n for n in allNodes if n.selected]
						# self._drag_offset = (node.x - cpx, round((node.y - cpy)/20)*20)
						self._drag_offset = (0, 0)
						self.bubbles['nodesBeforeDragL'] = [(n.x, n.y) for n in self.bubbles['nodesL']]
						self.bubbles['nodesBeforeDragR'] = [(n.x, n.y) for n in self.bubbles['nodesR']]
						# print(f"mouseDown_ hit node index {hit_index}, begin drag, node layer=({node.x:.2f},{node.y:.2f})")

				else:  # CLICKED AN EMPTY SPACE, ADD NEW NODE IF IT'S ON A LINE SEGMENT
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
							sideName = 'nodesL'
							nodeAdded = True
						else:  # R IS MORE SELECTABLE (WHEN BOTH SHOULD BE SELECTABLE)
							nodes = nodesR
							closest = closestR
							sideName = 'nodesR'
							nodeAdded = True
					elif closestDeltaR <= clickRadiusAbsolute:  # IF ONLY closestR IS SELECTABLE
						nodes = nodesR
						closest = closestR
						sideName = 'nodesR'
						nodeAdded = True

					# CHECK IF THE CLOSEST NODE IS WITHIN CLICKABLE RADIUS
					# IF CLOSE ENOUGH, THAT'S A NEW NODE
					if nodeAdded is True:
						self.deselectNodes()  # DE-SELECT ALL
						# print('current master =', m)
						new_node = BubbleNode(closest[0], closest[1], m.italicAngle, m.xHeight)
						new_node.selected = True

						# INSERT AT CORRECT POS, NOT AT THE LAST INDEX
						nodes.append(new_node)
						self.bubbles[sideName] = sorted(nodes, key=lambda n: n.y)

						self._dragging = True
						# self._dragging_nodes = allNodes[len(allNodes) - 1]
						self._dragging_nodes = [allNodes[-1]]
						self._drag_offset = (0.0, 0.0)
						self.bubbles['nodesBeforeDragL'] = [(n.x, n.y) for n in self.bubbles['nodesL']]
						self.bubbles['nodesBeforeDragR'] = [(n.x, n.y) for n in self.bubbles['nodesR']]
						# print(f"mouseDown_ created new node at layer=({cpx:.2f},{cpy:.2f}) index {self._dragging_nodes}")

						self.saveNodesToLayer()

					else:  # clicked space is truly empty. Start drag selection
						if theEvent.modifierFlags() != 131074:
							self.deselectNodes()  # de-select all
						self._dragging = True
						self._dragging_nodes = []  # MAYBE SELECT THE NODE
						self._drag_offset = (0.0, 0.0)

				graphicView.redraw()
		except:
			print("mouseDown_ error: " + traceback.format_exc())

	@objc.python_method
	def isLayerEditable(self, side):  # returns if layer is exporting and not automatically built
		try:
			# side IS EITHER 'L' or 'R'
			userData = self.activeLayer.userData
			if 'BubbleKernExport' + side in userData:
				if userData['BubbleKernExport' + side] is True:  # IF EXPORTS
					if 'BubbleKernInherit' + side in userData:
						if userData['BubbleKernInherit' + side] == '':  # IF IT DOESN'T INHERIT ANYTHING
							return True
			return False
		except:
			print("isLayerEditable error: " + traceback.format_exc())

	def mouseDragged_(self, theEvent):
		# objc.super(SampleExtraHandles, self).mouseDragged_(theEvent)
		try:
			if not self._dragging:
				return
			allNodes = []
			# SAFE BUILDING OF allNodes
			if self.isLayerEditable('L'):
				allNodes += self.bubbles['nodesL']
			if self.isLayerEditable('R'):
				allNodes += self.bubbles['nodesR']
			# allNodes = self.bubbles['nodesL'] + self.bubbles['nodesR']

			allNodesBeforeDrag = []
			# nodesBeforeDragL MAY BE NON-EXISTANT ON A NEW LAYER AND USING REFERENCE GLYPH
			if self.isLayerEditable('L') and 'nodesBeforeDragL' in self.bubbles:
				allNodesBeforeDrag += self.bubbles['nodesBeforeDragL']
			if self.isLayerEditable('R') and 'nodesBeforeDragR' in self.bubbles:
				allNodesBeforeDrag += self.bubbles['nodesBeforeDragR']
			# allNodesBeforeDrag = self.bubbles['nodesBeforeDragL'] + self.bubbles['nodesBeforeDragR']
			# BEFOREDRAG NODES ARE JUST TUPLES OF (X, Y)

			graphicView = self.editViewController().graphicView()
			if layer := graphicView.activeLayer():
				scale = graphicView.scale()
				currentPos = graphicView.getActiveLocation_(theEvent)
				dragOrigin = self._mouseDownPos  # just a tuple, cannot use .x .y
				self._drag_offset = (currentPos.x - dragOrigin[0], currentPos.y - dragOrigin[1])

				if self._dragging_nodes != []:  # if dragging a selected node. NEED TO SUPPORT MULTI DRAG

					for n in self._dragging_nodes:
						nodeOrigin = allNodesBeforeDrag[allNodes.index(n)]
						# print('coordinates:', nodeOrigin[0], nodeOrigin[1], nodeCurrent.x, nodeCurrent.y)
						n.x, n.y = int(round(nodeOrigin[0] + self._drag_offset[0])), int(round(nodeOrigin[1] + self._drag_offset[1]))

					# if DEBUG_COORDS:
					# 	print(f"mouseDragged_: moving node[{self._dragging_nodes}] to layer=({node.x:.2f},{node.y:.2f})")

				else:  # IF DRAGGING TO SELECT NODES
					dragBoxX = (dragOrigin[0], currentPos.x)
					dragBoxY = (dragOrigin[1], currentPos.y)
					minX, maxX = min(dragBoxX), max(dragBoxX)
					minY, maxY = min(dragBoxY), max(dragBoxY)

					if theEvent.modifierFlags() != 131074:  # if SHIFT is not being pressed
						for n in allNodes:
							n.selected = False
					for n in allNodes:
						# print(f"min ({minX},{minY}), max({maxY},{maxY}), node({n.x}, {n.y})")
						if minX <= n.x <= maxX:
							if minY <= n.y <= maxY:
								n.selected = True
					# print([n.selected for n in self.bubbles['nodesL']])

			Glyphs.redraw()
		except Exception:
			print("mouseDragged_ error: " + traceback.format_exc())

	def mouseUp_(self, theEvent):
		# objc.super(SampleExtraHandles, self).mouseUp_(theEvent)
		graphicView = self.editViewController().graphicView()
		try:
			if self._dragging and self._dragging_nodes is not None:
				if layer := graphicView.activeLayer():
					for n in self._dragging_nodes:
						n.x, n.y = int(round(n.x)), int(round(n.y))
					self.bubbles['nodesL'] = sorted(self.bubbles['nodesL'], key=lambda n: n.y)
					self.bubbles['nodesR'] = sorted(self.bubbles['nodesR'], key=lambda n: n.y)
					self.saveNodesToLayer()

			self._dragging = False
			self._dragging_nodes = None
			self._drag_offset = (0.0, 0.0)
			self.bubbles['nodesBeforeDragL'] = []
			self.bubbles['nodesBeforeDragR'] = []
			self._mouseDownPos = (0, 0)
			Glyphs.redraw()
			# print("mouseUp_ finished dragging")
		except Exception:
			print("mouseUp_ error: " + traceback.format_exc())

	def keyDown_(self, theEvent):  # when keyboard is pressed
		try:
			graphicView = self.editViewController().graphicView()
			layer = graphicView.activeLayer()
			allNodes = self.bubbles['nodesL'] + self.bubbles['nodesR']
			keyCode = theEvent.keyCode()
			modifier = theEvent.modifierFlags()
			# print('keyDown_', theEvent, keyCode, modifier)
			# if theEvent.modifierFlags() == 256: # nothing pressed
			# if theEvent.modifierFlags() == 131330: # shift is being pressed
			# if theEvent.modifierFlags() == 524576: # option
			# if theEvent.modifierFlags() == 262401: # control
			# if theEvent.modifierFlags() == 655650: # option + shift

			# if theEvent.keyCode() == 0: A


			# Move nodes by arrow keys
			if keyCode in (123, 124, 125, 126):
				multiplier = 1
				if theEvent.modifierFlags() in (131330, 10617090):  # WHEN SHIFT IS PRESSED
					multiplier = 10
				elif theEvent.modifierFlags() == 11534600:  # WHEN COMMAND IS PRESSED
					multiplier = 100

				# 10617090 is for Toshi's custom keyboard
				for n in allNodes:
					if n.selected:
						if keyCode == 123:  # LEFT
							n.x += -1 * multiplier
						elif keyCode == 124:  # RIGHT
							n.x += 1 * multiplier
						elif keyCode == 125:  # DOWN
							n.y += -1 * multiplier
						else:                # UP
							n.y += 1 * multiplier

			# TAB. CYCLE THROUGH NODES.
			elif theEvent.keyCode() == 48:
				# IF SHIFT IS BEING PRESSED, REVERSE THE ORDER
				allNodes = allNodes[::-1] if theEvent.modifierFlags() == 131330 else allNodes
				for n in allNodes:  # find the first instance of selection
					if n.selected:
						break
				self.deselectNodes()
				newIndex = (allNodes.index(n) - 1) % len(allNodes)
				allNodes[newIndex].selected = True

			# DELETE KEY
			elif theEvent.keyCode() == 51:
				for side in ('nodesL', 'nodesR'):
					# cannot delete directly; gather indexes first
					nodesToDelete = [i for i, n in enumerate(self.bubbles[side]) if n.selected]
					# go on to delete
					for i in reversed(nodesToDelete):
						self.bubbles[side].pop(i)

					# all deleted, give default bubble shape. 1 remaining is basically all delete.
					if len(self.bubbles[side]) <= 1:

						# MAYBE GIVE RESET WARNING BEFOREHAND?

						m = self.font.selectedFontMaster
						self.bubbles[side] = [BubbleNode(0, m.descender, m.italicAngle, m.xHeight), BubbleNode(0, m.ascender, m.italicAngle, m.xHeight)]

				self.saveNodesToLayer()

			# PASS OTHERS TO GLYPHS
			else:
				super().keyDown_(theEvent)

			Glyphs.redraw()
		except Exception:
			print("keyDown_ error: " + traceback.format_exc())

	@objc.python_method
	def validateInheritGlyph(self, layer, side):
		try:
			# expect 'L' or 'R' for side
			mId = layer.associatedMasterId
			if self.activeLayer.userData['BubbleKernInherit' + side]:  # IF INHERIT ENTRY EXISTS
				gName = self.activeLayer.userData['BubbleKernInherit' + side]
				if self.font.glyphs[gName]:                         # REFERRED GLYPH NAME IS VALID
					referredLayer = self.font.glyphs[gName].layers[mId]
					if 'BubbleKernInherit' + side in referredLayer.userData:  # CHECK NESTED INHERITANCE
						if referredLayer.userData['BubbleKernInherit' + side] != '':  # NEST CONFIRMED
							if self.validateInheritGlyph(referredLayer, side):
								return True
							else:
								return False
						elif 'BubbleKernNodes' + side in referredLayer.userData:  # ASSUMED SAFE AT THIS POINT
							return True
					else:  # REFERRED LAYER HAS NO BUBBLEKERN USERDATA
						return False
				else:
					return False
			else:
				return False
		except:
			traceback.print_exc()

	# CALLED WHEN SELECT ALL HAS BEEN CALLED FROM THE APP
	def selectAll_(self, sender):
		for side in ('nodesL', 'nodesR'):
			if self.activeLayer.isAligned is False:
				if side == 'nodesL' and self.validateInheritGlyph(self.activeLayer, 'L'):
					continue
				if side == 'nodesR' and self.validateInheritGlyph(self.activeLayer, 'R'):
					continue
				# IF NOT AUTO-ALIGNED OR INHERITED
				for node in self.bubbles[side]:
					node.selected = True
		Glyphs.redraw()

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

		# get selection size
		allNodes = self.bubbles['nodesL'] + self.bubbles['nodesR']
		selectedNodes = [n for n in allNodes if n.selected]
		if len(selectedNodes) > 1:  # if there are 2 or more nodes selected

			xCoords = [n.x for n in selectedNodes]
			xMin, xMax = min(xCoords), max(xCoords)

			yCoords = [n.y for n in selectedNodes]
			yMin, yMax = min(yCoords), max(yCoords)

			if xMax - xMin < yMax - yMin:  # TALLER SELECTION BOX; FLATTEN X VALUES
				if alignment in (0, 3, 6):   # X MININUM
					alignX = int(round(xMin))
				elif alignment in (1, 4, 7):  # X CENTRE
					alignX = int(round(xMin + (xMax - xMin) / 2))
				else:                      # X MAX
					alignX = int(round(xMax))
				for n in selectedNodes:
					n.x = alignX
			else:                     # WIDER SELECTION BOX; FLATTEN Y VALUES
				if alignment in (0, 1, 1):   # Y MINIMUM
					alignY = int(round(yMin))
				elif alignment in (3, 4, 5):  # Y CENTRE
					alignY = int(round(yMin + (yMax - yMin) / 2))
				else:                      # Y MAX
					alignY = int(round(yMax))
				for n in selectedNodes:
					n.y = alignY
			Glyphs.redraw()

	# def delSelectionWithModifier_(self, modifierFlag):
	# 	graphicView = self.editViewController().graphicView()
	# 	if layer := graphicView.activeLayer():
	# 		extraHandles = self.extraHandles() or []
	# 		self.setExtraHandles_(
	# 			[h for h in extraHandles if not layer.selectionContainsObject_(h)]
	# 		)
	# 		self.updateLayerSampleInfo(layer)
	# 		graphicView.redraw()

	# def lockNodeToSB_(self, sender):
	# 	print('context menu called')

	@objc.python_method
	def eraseBubble(self, sender):
		try:
			ud = self.activeLayer.userData
			if sender == self.w.group.menusL:
				bubbleKeys = ('BubbleKernInheritL', 'BubbleKernExportL', 'BubbleKernNodesL')
			else:
				bubbleKeys = ('BubbleKernInheritR', 'BubbleKernExportR', 'BubbleKernNodesR')
			for key in bubbleKeys:
				del ud[key]
		except:
			pass

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
