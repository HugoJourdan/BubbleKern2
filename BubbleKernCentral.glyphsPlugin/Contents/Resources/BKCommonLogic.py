# encoding: utf-8

# import Glyphs
import traceback
from AppKit import NSAffineTransform
from dataclasses import dataclass, field

# THIS IS WHERE THE SHARED BACKEND CODE SHOULD BE STORED
# SUCH AS CALCULATING THE BUBBLE SHAPE, DEALING WITH INHERITED (I.E. COMPONENT) BUBBLES.

@dataclass()
class layerAttributes:
	bubble: GSLayer = None
	transform: tuple = None
	children: list[int] = field(default_factory=list) # another layerAttributes?
	depth: int = 0

# IF MULTIPLE BUBBLES EXIST AND NEED TO BE COMBINED
def combineBubbles():
	pass

# hopefully new implementation of collectBubbleShapes
def gatherBubbleInfo(layer, side:str): # SIDE IS EITHER L/R
	pass
	# check if layer is auto-aligned
	# collect bubbles for each layer (nest?)

	# if not auto-aligned, check if it refers to a glyph
	# collect bubbles for each layer (nest?)

	# if neither auto-aligned or inheriting, mark the end of search

# 
def buildBubble2():
	pass



# NEED TO RESTRUCTURE! MAYBE UNNECESSARY
# IT NEEDS TO BE DONE ON EACH SIDE.
def collectBubbleShapes(layer, theTransform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0):
	# FOR GETTING ACCUMULATED ATTRIBUTES FROM NESTED BUBBLES.
	# INPUT LAYER, TRANSFORM, AND CURRENT BUBBLE PURSUIT LEVEL.
	# RETURNS A LAYER ATTRIBUTES INSTANCE.
	try:
		m = layer.associatedFontMaster()
		thePath = None
		children = []
		for side in ('BubbleKernInheritL', 'BubbleKernInheritR'):
			if layer.userData[side]: # if bubble data exists in the layer
				for c in layer.components:
					children.append(self.collectBubbleShapes(c.componentLayer, c.transform, depth+1))

		matched = False # deepest bubble layer found status

		for l in layer.parent.layers:
			if l.isMasterLayer and l.associatedFontMaster() == m:
				for side in ('BubbleKernNodesL', 'BubbleKernNodesR'):
					if nodes in l.userData:
						if len(l.userData[side]) > 0: # bubble nodes exist
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


def buildBubble(theAttributes, bubblePath=None, inheritedTransforms=[], lastDepth=0, isLeft=True):
	# RECEIVES BUBBLE ATTRIBUTES AND PATH TO BUILD A BUBBLE.
	# MODIFIES bubblePath DIRECTLY.
	try:
		# FIRST RUN
		if bubblePath == None:
			bubblePath = NSBezierPath.alloc().init()

		# NEED TO ADD AUTOMATIC BUILD

		if theAttributes.children: # IF THERE ARE COMPONENTS
			for c in theAttributes.children: # c = ANOTHER ATTRIBUTE
				if theAttributes.transform is not None:
					inheritedTransforms.append(theAttributes.transform)
				self.buildBubble(c, bubblePath, inheritedTransforms)

		bubbleLayer = theAttributes.bubble # THE BUBBLE
		if isLeft == True and 'BubbleKernNodesL' in bubbleLayer.userData:
			nodes = bubbleLayer.userData['BubbleKernNodesL']
		elif isLeft == False and 'BubbleKernNodesR' in bubbleLayer.userData:
			nodes = bubbleLayer.userData['BubbleKernNodesR']

		# WHAT HAPPENS IN MULTIPLE BUBBLES ?
		currentDepth = theAttributes.depth
		for i, n in enumerate(nodes):
			if i == 0: # if first node
				bubblePath.moveToPoint_( NSPoint(n[0], n[1]) )
			else:
				bubblePath.lineToPoint_( NSPoint(n[0], n[1]) )

		inheritedTransforms.append(theAttributes.transform)
		for t in inheritedTransforms:
			trans = NSAffineTransform()
			trans.setTransformStruct_(t)

			trans.transformBezierPath_(bubblePath)

		for i in range(currentDepth-lastDepth):
			if inheritedTransforms:
				inheritedTransforms.pop(-1)
		lastDepth = currentDepth

		return bubblePath
	except:
		print('buildBubble error: ', traceback.format_exc())

