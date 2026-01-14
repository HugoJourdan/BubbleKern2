# encoding: utf-8

# IT EXISTS HERE SO THAT THE USER CAN ACCESS THE BUBBLE VIEW OUTSIDE THE BUBBLEKERN TOOL.
# EITHER IT NEEDS TO SHARE THE SAME DRAWING FUNCTIONS WITH THE TOOL, OR I DECIDE TO REMOVE THE REPORTER COMPLETELY.
# CURRENTLY IT IS NOT BEING ACTIVELY DEVELOPED.

from __future__ import division, print_function, unicode_literals
import objc
from GlyphsApp import *
from GlyphsApp.plugins import *
import traceback
from dataclasses import dataclass, field
from AppKit import NSBezierPath

@dataclass()
class layerAttributes:
	bubble: GSLayer = None
	transform: tuple = None
	children: list[int] = field(default_factory=list) # another layerAttributes?
	depth: int = 0

class ShowKernBubbles4(ReporterPlugin):

	@objc.python_method
	def settings(self):
		self.menuName = Glyphs.localize({
			'en': 'Kern Bubbles 4',
			})
		# self.generalContextMenus = [{
		# 	'name': Glyphs.localize({
		# 		'en': 'Do something',
		# 		}), 
		# 	'action': self.doSomething_
		# 	}]


	@objc.python_method
	def collectBubbleShapes(self, layer, theTransform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0):
		# Input layer, transform, and bubble pursuit level.
		# Returns a layer attributes instance.
		try:
			m = layer.associatedFontMaster()
			thePath = None
			children = []
			for nodes in ('BubbleKernInheritL', 'BubbleKernInheritR'):
				if layer.userData[nodes]: # if bubble data exists in the layer
					# NEED TO REWRITE SO THAT IT ONLY INHERITS WHEN AUTOMATIC
					for c in layer.components:
						children.append(self.collectBubbleShapes(c.componentLayer, c.transform, depth+1))

			matched = False # deepest bubble layer found status

			for l in layer.parent.layers:
				if l.isMasterLayer and l.associatedFontMaster() == m:
					for nodes in ('BubbleKernNodesL', 'BubbleKernNodesR'):
						if nodes in l.userData:
							if len(l.userData[nodes]) > 0: # bubble nodes exist
								matched = True
								break
					break
			if matched:
				currentAttributes = layerAttributes(l, theTransform, children, depth)
				return currentAttributes
			else:
				return False
		except:
			print('collectBubbleShapes error: ', traceback.format_exc())

	@objc.python_method
	def buildBubble(self, theAttributes, bubblePath, inheritedTransforms=[], lastDepth=0, isLeft=True):
		# receives bubble attributes, li (imaginary layer) to build a bubble, parent attributes.
		# Adds bubble shape to the li.
		try:
			if theAttributes.children: # if there are components
				for c in theAttributes.children: # c = attribute
					if theAttributes.transform is not None:
						inheritedTransforms.append(theAttributes.transform)
					self.buildBubble(c, bubblePath, inheritedTransforms)

			bubbleLayer = theAttributes.bubble # the bubble
			if isLeft == True and 'BubbleKernNodesL' in bubbleLayer.userData:
				nodes = bubbleLayer.userData['BubbleKernNodesL']
			elif isLeft == False and 'BubbleKernNodesR' in bubbleLayer.userData:
				nodes = bubbleLayer.userData['BubbleKernNodesR']

			# if 'BubbleKernNodesL' in bubbleLayer.userData or 'BubbleKernNodesR' in bubbleLayer.userData:
			currentDepth = theAttributes.depth
			for i, n in enumerate(nodes):
				if i == 0: # if first node
					bubblePath.moveToPoint_( NSPoint(n[0], n[1]) )
				else:
					bubblePath.lineToPoint_( NSPoint(n[0], n[1]) )
					# bubblePath.close_()
			inheritedTransforms.append(theAttributes.transform)
			for t in inheritedTransforms:
				trans = NSAffineTransform()
				trans.setTransformStruct_(t)
				# bubblePath.transform_(trans) # transform?
				trans.transformBezierPath_(bubblePath)
			# for s in bubbleCopy.shapes: # what was the purpose of this?
			# 	li.shapes.append(s.copy())
			for i in range(currentDepth-lastDepth):
				if inheritedTransforms:
					inheritedTransforms.pop(-1)
			lastDepth = currentDepth
			
		except:
			print('buildBubble error: ', traceback.format_exc())

	@objc.python_method
	def inactiveLayerBackground(self, layer): # drawing for non-main glyphs
		try:
			scale = Glyphs.font.currentTab.scale
			if scale > 0.1: # if above 100 pts when text metrics also disappear
				# defaultColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.4, 1.0, 0.25)
				# defaultColor.set()

				# ideal implementation
				# leftColor = NSColor.systemCyanColor().colorWithAlphaComponent_(0.5)
				# rightColor = NSColor.systemPinkColor().colorWithAlphaComponent_(0.5)

				# attributes of layers holding bubbles (including inherited), not the actual paths
				theBubbles = self.collectBubbleShapes(layer)
				if theBubbles:
					bubblePathL = NSBezierPath.alloc().init()
					self.buildBubble(theAttributes=theBubbles, bubblePath=bubblePathL, inheritedTransforms=[], lastDepth=0, isLeft=True)
					NSColor.systemCyanColor().colorWithAlphaComponent_(0.5).set()
					bubblePathL.setLineWidth_( 2/scale )
					bubblePathL.stroke()

					bubblePathR = NSBezierPath.alloc().init()
					self.buildBubble(theAttributes=theBubbles, bubblePath=bubblePathR, inheritedTransforms=[], lastDepth=0, isLeft=False)
					# BUBBLE R IS STORED BASED ON GLYPH WIDTH. NEED TO OFFSET BY THE WIDTH VALUE
					transform = NSAffineTransform.transform()
					transform.translateXBy_yBy_(layer.width, 0)
					bubblePathR.transformUsingAffineTransform_(transform)

					NSColor.systemPinkColor().colorWithAlphaComponent_(0.5).set()
					bubblePathR.setLineWidth_( 2/scale )
					bubblePathR.stroke()

		except:
			print('inactiveLayerBackground error: ', traceback.format_exc())

	@objc.python_method
	def background(self, layer): # drawing for the main glyph
		try:
			theController = Glyphs.currentDocument.windowController()
			toolEventHandler = theController.toolEventHandler()
			toolIsHandTool = toolEventHandler.className() == "GlyphsToolHand"
			toolIsTextTool = toolEventHandler.className() == "GlyphsToolText"
			if toolIsHandTool or toolIsTextTool:
				# NEED TO DRAW PATH
				pass

		except:
			print('background error: ', traceback.format_exc())


	def doSomething_(self, sender): # unused
		print('Just did something')

	@objc.python_method
	def conditionalContextMenus(self):

		# Empty list of context menu items
		contextMenus = []

		# Execute only if layers are actually selected
		if Glyphs.font.selectedLayers:
			layer = Glyphs.font.selectedLayers[0]
			
			# Exactly one object is selected and it’s an anchor
			if len(layer.selection) == 1 and type(layer.selection[0]) == GSAnchor:
				pass
				# Add context menu item
				# contextMenus.append({
				# 	'name': Glyphs.localize({
				# 		'en': 'Do something else',
				# 		'de': 'Tu etwas anderes',
				# 		'fr': 'Faire aute chose',
				# 		'es': 'Hacer algo más',
				# 		'pt': 'Faça outra coisa',
				# 		}), 
				# 	'action': self.doSomethingElse_
				# 	})

		# Return list of context menu items
		return contextMenus

	# def doSomethingElse_(self, sender):
	# 	print('Just did something else')

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
