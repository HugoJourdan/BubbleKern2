# encoding: utf-8

from GlyphsApp import GSLayer
import traceback
from Foundation import NSAffineTransform, NSPoint, NSBezierPath
from AppKit import NSBezierPath
from dataclasses import dataclass, field
from typing import Optional

# THIS IS WHERE THE SHARED BACKEND CODE SHOULD BE STORED
# SUCH AS CALCULATING THE BUBBLE SHAPE, DEALING WITH INHERITED (I.E. COMPONENT) BUBBLES.

referKeyL = 'BubbleKernReferL'
referKeyR = 'BubbleKernReferR'
nodesKeyL = 'BubbleKernNodesL'
nodesKeyR = 'BubbleKernNodesR'
defaultTransform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

@dataclass()
class layerAttributes:
	layer: Optional[GSLayer] = None
	transform: Optional[tuple] = None
	# children: list[int] = field(default_factory=list)  # another layerAttributes?
	children: list["layerAttributes"] = field(default_factory=list)
	refers: bool = False
	depth: int = 0

# called from getFinalBubble()
# def collectBubbleShapes(layer, theTransform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0) -> layerAttributes | None:
def gatherBubbleInfo(layer, theTransform=defaultTransform, refers=False, depth=0, isLeft=True) -> layerAttributes | None:
	# FOR GETTING ACCUMULATED ATTRIBUTES FROM NESTED BUBBLES.
	# INPUT LAYER, TRANSFORM, AND CURRENT BUBBLE PURSUIT LEVEL.
	# RETURNS A LAYER ATTRIBUTES INSTANCE.
	try:
		f = layer.font()
		m = layer.associatedFontMaster()

		children = [] # info for components in the layer
		side = referKeyL if isLeft else referKeyR
		if layer.userData[side]: # if reference exists
			refers = True
			gName = layer.userData[side]
			if f.glyphs[gName]: # if glyph name is valid
				# get the gName layer's bubble info
				referredLayer = f.glyphs[gName].layers[layer.associatedMasterId]
				children.append(gatherBubbleInfo(referredLayer, defaultTransform, False, depth + 1))
		else: # reference doesn't exist; look for components
			for c in layer.components: # if reference doesn't exist, chase down components
				children.append(gatherBubbleInfo(c.componentLayer, c.transform, False, depth + 1))

		matched = False  # deepest bubble layer found status: False as default
		for l in layer.parent.layers: # make sure to find master layer
			if l.isMasterLayer and l.associatedFontMaster() == m:
				break
		side = nodesKeyL if isLeft else nodesKeyR
		if side in l.userData:
			if len(l.userData[side]) > 0:  # bubble nodes exist
				return layerAttributes(l, theTransform, children, refers, depth)
		# match=True without a bubble; return None
		return None
	except:
		print('gatherBubbleInfo error: ', traceback.format_exc())

# called from getFinalBubble()
# using layer & bubble info obtained from gatherBubbleInfo(), put all bubbles into one layer
def buildBubble(theAttributes, isLeft=True, bubblePath=None, inheritedTransforms=[], lastDepth=0) -> NSBezierPath:
	# RECEIVES BUBBLE ATTRIBUTES AND PATH TO BUILD A BUBBLE.
	# MODIFIES bubblePath DIRECTLY.
	try:
		# FIRST RUN
		if bubblePath is None:
			bubblePath = NSBezierPath.alloc().init()
		# print()
		indent = '\t' * theAttributes.depth
		# print(f'{indent}buildBubble working on {theAttributes.layer.parent.name}')
		# print(f'{indent}', theAttributes)
		if theAttributes.children != []:  # IF THERE ARE REFERENCES OR COMPONENTS
			# print(f'{indent}component or reference found')
			for child in theAttributes.children:  # c = ANOTHER ATTRIBUTE
				if theAttributes.transform is not None:
					inheritedTransforms.append(theAttributes.transform)

					# Potential fix point
					bubblePath.appendBezierPath_(buildBubble(child, isLeft, bubblePath, inheritedTransforms))
		# else:
			# print(f'{indent}reference/components not found in {theAttributes.layer.parent.name}')

		currentDepth = theAttributes.depth

		if theAttributes.refers == False: # if path or component; no referred glyphs
			# print(f'{indent}adding bubble paths')
			bubbleLayer = theAttributes.layer  # THE BUBBLE 
			if isLeft:
				try: # try loading from tempData first
					nodes = bubbleLayer.tempData['bubbles']['nodesL']
					nodes = [(n.x, n.y) for n in sorted(nodes, key = lambda node: node.y)] # SORT NODES BY HEIGHT
					# if loaded from tempData, the nodes ma not be in height order yet
					# (particularly while dragging)
				except:
					nodes = bubbleLayer.userData[nodesKeyL]
			else:
				try:
					nodes = bubbleLayer.tempData['bubbles']['nodesR']
					wid = bubbleLayer.tempData['bubbles']['width']
					nodes = [(n.x-wid, n.y) for n in sorted(nodes, key = lambda node: node.y)] # SORT NODES BY HEIGHT
					# TEMPDATA'S NODE POS INCLUDES WIDTH; REMOVE IT HERE
				except:
					nodes = bubbleLayer.userData[nodesKeyR]

			for i, n in enumerate(nodes):
				if i == 0:  # if first node
					bubblePath.moveToPoint_(NSPoint(n[0], n[1]))
				else:
					bubblePath.lineToPoint_(NSPoint(n[0], n[1]))
		# else:
		# 	print(f'{indent}bubble paths not found in {theAttributes.layer.parent.name}')

		inheritedTransforms.append(theAttributes.transform)
		for t in inheritedTransforms:
			trans = NSAffineTransform()
			trans.setTransformStruct_(t)
			trans.transformBezierPath_(bubblePath)
		for i in range(currentDepth - lastDepth):
			if inheritedTransforms:
				inheritedTransforms.pop(-1)
		lastDepth = currentDepth
		# print(f'{indent}returning path from {theAttributes.layer.parent.name}:', bubblePath)

		return bubblePath
	except:
		print('buildBubble error: ', traceback.format_exc())

# def bubblePathFromNodes(nodes) -> NSBezierPath:
# 	bubblePath = NSBezierPath.alloc().init()
# 	for i, n in enumerate(nodes):
# 	if i == 0:  # if first node
# 		bubblePath.moveToPoint_(NSPoint(n[0], n[1]))
# 	else:
# 		bubblePath.lineToPoint_(NSPoint(n[0], n[1]))
# 	return bubblePath

# COMBINING MULTIPLE OUTLINES TO ONE

# segment a-b, and node p. Return which side of segment p is on.
# left if return value > 0, right if < 0, bang on if == 0
def orientation(a, b, p):
	# sort by y coordinate to make sure a is lower
	a,b = sorted((a,b), key = lambda node: node.y)
	return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)

# find second leftmost node. i.e. x coordinate of segment at given y
def x_at_nodeYPos(a, b, node):
	y = node.y
	if b.y == a.y:
		return None  # horizontal line: either infinite or no solution
	t = (y - a.y) / (b.y - a.y)
	return a.x + t * (b.x - a.x)

# "segment" contains sgment and check node.
def segmentOverlapCheck(segment):
	path = segment[0].parent
	n0, n1, n2 = segment
	if len(path.nodes) > 2: # if more than two nodes:
		if path.nodes[0] in (n0, n1) and path.nodes[-1] in (n0, n1):
		# need to check if the segment is a legitimately neighbouring nodes
		# if path's start and end nodes are the segment; wrong
			return False
	if min(n0.y, n1.y) <= n2.y <= max(n0.y, n1.y):
		return True
	return False # need to return some default value


# INTERSECTION FINDING

# Ultimately used only for segment_intersection()
# returns if node p is between segment a-b's bounds
def between_segment(a, b, p):
	return (min(a.x, b.x) <= p.x <= max(a.x, b.x) and min(a.y, b.y) <= p.y <= max(a.y, b.y))

# Ultimately used only for segment_intersection()
# returns if segments a-b and c-d intersect
def if_segments_intersect(a, b, c, d): # segment a-b and c-d
	o1 = orientation(a, b, c)
	o2 = orientation(a, b, d)
	o3 = orientation(c, d, a)
	o4 = orientation(c, d, b)

	# Proper intersection
	if o1 * o2 < 0 and o3 * o4 < 0:
		return True

	# Collinear cases
	if o1 == 0 and between_segment(a, b, c): return True
	if o2 == 0 and between_segment(a, b, d): return True
	if o3 == 0 and between_segment(c, d, a): return True
	if o4 == 0 and between_segment(c, d, b): return True

	return False

# Ultimately used only for segment_intersection()
# calculate intersection assuming the segments are known to intersect
def intersection_point(a, b, c, d):
	x1, y1 = a
	x2, y2 = b
	x3, y3 = c
	x4, y4 = d

	denom = (x1 - x2)*(y3 - y4) - (y1 - y2)*(x3 - x4)
	if denom == 0:
		return None  # parallel or collinear

	px = ((x1*y2 - y1*x2)*(x3 - x4) - (x1 - x2)*(x3*y4 - y3*x4)) / denom
	py = ((x1*y2 - y1*x2)*(y3 - y4) - (y1 - y2)*(x3*y4 - y3*x4)) / denom
	if px in (a.x, b.x, c.x, d.x): # if px is among the segments' endpoints
		return None
	if py in (a.y, b.y, c.y, d.y): # if py is among the segments' endpoints
		return None
	return (round(px), round(py))

# if segments a-b and c-d intersect, return coordinates
def segment_intersection(segment0, segment1):
	a, b = segment0[0], segment0[1]
	c, d = segment1[0], segment1[1]
	if not if_segments_intersect(a, b, c, d):
		return None

	p = intersection_point(a, b, c, d)
	if p is not None:
		return p

	# Collinear overlap — intersection is a segment, not a point
	return None

# / INTERSECTION FINDER


# build single bubble wall from multiple sources
def getSingleBubbleWall( paths, side ):

	openPaths = [p for p in layer.paths if p.closed == False]

	# add crossed nodes
	intersections = []
	allSegs = [seg for p1 in openPaths for seg in p1.segments]
	for seg0 in allSegs:
		for seg1 in allSegs:
			try:
				intersection = segment_intersection(seg0,seg1)
				if intersection != None:
					intersections.append(intersection)
			except:
				traceback.print_exc()


	# check if any node is leftmost?
	leftmostNodes = []
	for p in openPaths: # vertical order not guaranteed
		for n in p.nodes:
			nodeInside = False
			# segs = all segments in the path
			segs = [seg for p1 in openPaths for seg in p1.segments]
			for seg in segs:
				segYs = (seg[0].y, seg[1].y)
				if min(segYs) <= n.y <= max(segYs): # if n within y bounds of segment
					if orientation(seg[0], seg[1], n) < 0: # 0 if on the line, right if more than 0
						nodeInside = True

			if nodeInside == False:
				leftmostNodes.append(n)

	# sorting by verticality FROM BOTTOM; may not be necessary depending on the setup
	leftmostNodes = sorted(leftmostNodes, key = lambda node: node.y)


	# check if there is any jump between paths
	# if jumps across between open paths (i.e. jump to the edge of path)
	# if jumps mid another path
	nodesToAdd = []
	for i, n in enumerate(leftmostNodes): # checking from top to bottom
		if i == 0:
			continue
		prevNode = leftmostNodes[i-1]
		thisPath, prevPath = n.parent, prevNode.parent
		if thisPath != prevPath: # jump ocurring
			# print('jumping!', n.y, prevNode.y)
			# gap between paths
			prevPathTop = prevPath.bounds[0][1]+prevPath.bounds[1][1]
			thisPathBtm = thisPath.bounds[0][1]
			print(prevPathTop, thisPathBtm)

			if prevPathTop < thisPathBtm: # open gap
				# print('\topen or crossing?')
				if n.x <= prevNode.x: # current node is more right (inside)
					nodesToAdd.append((i, NSPoint(prevNode.x, n.y)))
				else:
					nodesToAdd.append((i, NSPoint(n.x, prevNode.y)))
					

			elif prevPathTop >= thisPathBtm: # overlapping and touching
				# print('\toverlapping')
				
				segCandidates = (
					# new node among the previous path
					(prevNode, prevNode.prevNode, n),
					(prevNode, prevNode.nextNode, n),
					# new node among the current path
					(n, n.prevNode, prevNode),
					(n, n.nextNode, prevNode))
				for seg in segCandidates:
					if segmentOverlapCheck(seg):
						#print('good one', seg)
						newX = x_at_nodeYPos(seg[0], seg[1], seg[2])
						nodesToAdd.append((i, NSPoint(newX, seg[2].y)))
						break


	for n in reversed(nodesToAdd):
		index, node = n
		leftmostNodes.insert(index, node)

	bp = NSBezierPath.alloc().init()
	bp.moveToPoint_((leftmostNodes[0].x, leftmostNodes[0].y))
	for n in leftmostNodes[1:]:
		bp.lineToPoint_((n.x, n.y))
	
	return bp


# Called from outside; returns the singular bubble line (ideally)
def getFinalBubble(layer, isLeft=True) -> NSBezierPath:
	# look for the bubble information for all components
	bubbleAttributes = gatherBubbleInfo(layer, isLeft=isLeft)
	# print()
	# print(layer.parent.name)
	# print(bubbleAttributes)
	if bubbleAttributes:
		bp = buildBubble(theAttributes=bubbleAttributes, isLeft=isLeft, bubblePath=None, inheritedTransforms=[], lastDepth=0)
		# buildBubble contains multiple lines; need to get a single line
		# getSingleBubbleWall()
		if isLeft == False: # on the right, move bubble
			transform = NSAffineTransform.transform()
			transform.translateXBy_yBy_(layer.width, 0)   # move by dx horizontally
			bp.transformUsingAffineTransform_(transform)
		return bp

	# emergency pass through
	# side = nodesKeyL if isLeft else nodesKeyR
	# nodes = layer.userData[nodesKeyL]
	# bubblePath = NSBezierPath.alloc().init()
	# for i, n in enumerate(nodes):
	# 	if i == 0:  # if first node
	# 		bubblePath.moveToPoint_(NSPoint(n[0], n[1]))
	# 	else:
	# 		bubblePath.lineToPoint_(NSPoint(n[0], n[1]))
	# 	return bubblePath