# encoding: utf-8

from GlyphsApp import Glyphs, GSLayer, GSPath
import traceback
from Foundation import NSAffineTransform, NSPoint
from AppKit import NSBezierPath, NSTextField
from Cocoa import NSAlert, NSAlertStyleCritical
from dataclasses import dataclass, field
from typing import Optional
from math import ceil, radians, tan

# THIS IS WHERE THE SHARED BACKEND CODE SHOULD BE STORED
# SUCH AS CALCULATING THE BUBBLE SHAPE, DEALING WITH INHERITED (I.E. COMPONENT) BUBBLES.

referKeyL = 'BubbleKernReferL'
referKeyR = 'BubbleKernReferR'
nodesKeyL = 'BubbleKernNodesL'
nodesKeyR = 'BubbleKernNodesR'
defaultTransform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# LOGGING
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
# / LOGGING


@dataclass()
class layerAttributes:
	layer: Optional[GSLayer] = None
	transform: Optional[tuple] = None
	# children: list[int] = field(default_factory=list)  # another layerAttributes?
	children: list["layerAttributes"] = field(default_factory=list)
	refers: bool = False
	depth: int = 0


# UI STUFF FOR SHOWING DIALOG
def show_alert(message: str, secondMessage: str = '', cancel: bool = True, askString: bool = False):
	alert = NSAlert.alloc().init()
	alert.setMessageText_(message)
	if secondMessage != '':
		alert.setInformativeText_(secondMessage)

	# --- Text field ---
	if askString:
		inputField = NSTextField.alloc().initWithFrame_(((0, 0), (240, 24)))
		inputField.setStringValue_('')
		alert.setAccessoryView_(inputField)

	alert.addButtonWithTitle_("OK")  # index 1000
	if cancel or askString:
		alert.addButtonWithTitle_("Cancel")  # index 1001

	if not askString: # not big triangle in askString message
		alert.setAlertStyle_(NSAlertStyleCritical)

	response = alert.runModal()
	if response == 1000:  # OK
		if askString:
			text = field.stringValue().strip() # strip removes white spaces from both ends of str
			if text:
				return inputField.stringValue()
			show_alert('Preset name cannot be empty or spaces only.', cancel=False)
		return True
	elif response == 1001:  # Cancel
		return False

# called from BKTool when getting node position for display; converts tempData's node x to userData's node x for display and storage
# also from buildBubble()
def tempToUserNodeX(x, y, italicAngle, xHeight):
	if italicAngle != 0:
		italicAngle = radians(90 - italicAngle)
		return x - (y - xHeight / 2) / tan(italicAngle)
	else:
		return x

# called from getFinalBubble()
# def collectBubbleShapes(layer, theTransform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0) -> layerAttributes | None:
def gatherBubbleInfo(layer, theTransform=defaultTransform, refers=False, depth=0, isLeft=True) -> layerAttributes | None:
	# FOR GETTING ACCUMULATED ATTRIBUTES FROM NESTED BUBBLES.
	# INPUT LAYER, TRANSFORM, AND CURRENT BUBBLE PURSUIT LEVEL.
	# RETURNS A LAYER ATTRIBUTES INSTANCE.
	try:
		f = layer.font()
		m = layer.associatedFontMaster()

		children = []  # info for components in the layer
		side = referKeyL if isLeft else referKeyR
		if layer.userData[side]:  # if reference exists
			refers = True
			gName = layer.userData[side]
			if f.glyphs[gName]:  # if glyph name is valid
				# get the gName layer's bubble info
				referredLayer = f.glyphs[gName].layers[layer.associatedMasterId]
				children.append(gatherBubbleInfo(referredLayer, defaultTransform, False, depth + 1))
		else:  # reference doesn't exist; look for components
			for c in layer.components:  # if reference doesn't exist, chase down components
				children.append(gatherBubbleInfo(c.componentLayer, c.transform, False, depth + 1))

		# matched = False  # deepest bubble layer found status: False as default
		for l in layer.parent.layers:  # make sure to find master layer
			if l.isMasterLayer and l.associatedFontMaster() == m:
				break
		side = nodesKeyL if isLeft else nodesKeyR
		if side in l.userData:
			if len(l.userData[side]) > 0:  # bubble nodes exist
				return layerAttributes(l, theTransform, children, refers, depth)
		# match=True without a bubble; return None
		return None
	except:
		log(f'gatherBubbleInfo error: {traceback.format_exc()}', error=True)

# called from getFinalBubble()
# using layer & bubble info obtained from gatherBubbleInfo(), put all bubbles into one layer
def buildBubble(theAttributes, isLeft=True, bubblePath=None, inheritedTransforms=None) -> NSBezierPath:
	# RECEIVES BUBBLE ATTRIBUTES AND PATH TO BUILD A BUBBLE.
	# MODIFIES bubblePath DIRECTLY.

	if bubblePath is None:
		bubblePath = NSBezierPath.alloc().init()
	if inheritedTransforms is None:
		inheritedTransforms = []
	try:
		currentTransforms = list(inheritedTransforms)
		if theAttributes.transform is not None:
			currentTransforms.append(theAttributes.transform)

		# indent = '\t' * theAttributes.depth
		# log(f'{indent}buildBubble working on {theAttributes.layer.parent.name}')
		# log(f'{indent} {theAttributes}')
		if theAttributes.children:  # IF THERE ARE REFERENCES OR COMPONENTS
			for child in theAttributes.children:
				buildBubble(child, isLeft, bubblePath, currentTransforms)
		# else:
			# log(f'{indent}reference/components not found in {theAttributes.layer.parent.name}')

		if theAttributes.refers is False:  # if path or component; no referred glyphs
			# log(f'{indent}adding bubble paths')
			bubbleLayer = theAttributes.layer  # THE BUBBLE
			m = bubbleLayer.associatedFontMaster()
			italicAngle = -m.italicAngle if m else 0
			localPath = NSBezierPath.alloc().init()
			
			if isLeft:
				try:  # try loading from tempData first
					nodes = bubbleLayer.tempData['bubbles']['nodesL']
					nodes = [(n.x, n.y) for n in sorted(nodes, key=lambda node: node.y)]  # SORT NODES BY HEIGHT
					# if loaded from tempData, the nodes ma not be in height order yet
					# (particularly while dragging)
				except:
					rawNodes = bubbleLayer.userData[nodesKeyL]
					nodes = [(tempToUserNodeX(n[0], n[1], italicAngle, m.xHeight), n[1]) for n in rawNodes]
			else:
				try:
					nodes = bubbleLayer.tempData['bubbles']['nodesR']
					wid = bubbleLayer.tempData['bubbles']['width']
					nodes = [(n.x - wid, n.y) for n in sorted(nodes, key=lambda node: node.y)]  # SORT NODES BY HEIGHT
					# TEMPDATA'S NODE POS INCLUDES WIDTH; REMOVE IT HERE
				except:
					rawNodes = bubbleLayer.userData[nodesKeyR]
					nodes = [(tempToUserNodeX(n[0], n[1], italicAngle, m.xHeight), n[1]) for n in rawNodes]

			for i, n in enumerate(nodes):
				if i == 0:  # if first node
					localPath.moveToPoint_(NSPoint(n[0], n[1]))
				else:
					localPath.lineToPoint_(NSPoint(n[0], n[1]))

			for t in currentTransforms:
				trans = NSAffineTransform()
				trans.setTransformStruct_(t)
				trans.transformBezierPath_(localPath)

			bubblePath.appendBezierPath_(localPath)
		# else:
		# 	log(f'{indent}bubble paths not found in {theAttributes.layer.parent.name}')
		# log(f'{indent}returning path from {theAttributes.layer.parent.name}: {bubblePath}')

	except:
		log(f'buildBubble error: {traceback.format_exc()}', error=True)

	return bubblePath

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
	a, b = sorted((a, b), key=lambda node: node.y)
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
	if len(path.nodes) > 2:  # if more than two nodes:
		if path.nodes[0] in (n0, n1) and path.nodes[-1] in (n0, n1):
			# need to check if the segment is a legitimately neighbouring nodes
			# if path's start and end nodes are the segment; wrong
			return False
	if min(n0.y, n1.y) <= n2.y <= max(n0.y, n1.y):
		return True
	return False  # need to return some default value


# INTERSECTION FINDING

# Ultimately used only for segment_intersection()
# returns if node p is between segment a-b's bounds
def between_segment(a, b, p):
	return (min(a.x, b.x) <= p.x <= max(a.x, b.x) and min(a.y, b.y) <= p.y <= max(a.y, b.y))

# Ultimately used only for segment_intersection()
# returns if segments a-b and c-d intersect
def if_segments_intersect(a, b, c, d):  # segment a-b and c-d
	o1 = orientation(a, b, c)
	o2 = orientation(a, b, d)
	o3 = orientation(c, d, a)
	o4 = orientation(c, d, b)

	# Proper intersection
	if o1 * o2 < 0 and o3 * o4 < 0:
		return True

	# Collinear cases
	if o1 == 0 and between_segment(a, b, c):
		return True
	if o2 == 0 and between_segment(a, b, d):
		return True
	if o3 == 0 and between_segment(c, d, a):
		return True
	if o4 == 0 and between_segment(c, d, b):
		return True

	return False

# Ultimately used only for segment_intersection()
# calculate intersection assuming the segments are known to intersect
def intersection_point(a, b, c, d):
	x1, y1 = a
	x2, y2 = b
	x3, y3 = c
	x4, y4 = d

	denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
	if denom == 0:
		return None  # parallel or collinear

	px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
	py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
	if px in (a.x, b.x, c.x, d.x):  # if px is among the segments' endpoints
		return None
	if py in (a.y, b.y, c.y, d.y):  # if py is among the segments' endpoints
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
# def getSingleBubbleWall(paths: list[GSPath], side):

# 	openPaths = [p for p in layer.paths if not p.closed]

# 	# add crossed nodes
# 	intersections = []
# 	allSegs = [seg for p1 in openPaths for seg in p1.segments]
# 	for seg0 in allSegs:
# 		for seg1 in allSegs:
# 			try:
# 				intersection = segment_intersection(seg0, seg1)
# 				if intersection is not None:
# 					intersections.append(intersection)
# 			except:
				# log(f'segment_intersection error: {traceback.format_exc()}', error=True)


# 	# check if any node is leftmost?
# 	leftmostNodes = []
# 	for p in openPaths:  # vertical order not guaranteed
# 		for n in p.nodes:
# 			nodeInside = False
# 			# segs = all segments in the path
# 			segs = [seg for p1 in openPaths for seg in p1.segments]
# 			for seg in segs:
# 				segYs = (seg[0].y, seg[1].y)
# 				if min(segYs) <= n.y <= max(segYs):  # if n within y bounds of segment
# 					if orientation(seg[0], seg[1], n) < 0:  # 0 if on the line, right if more than 0
# 						nodeInside = True

# 			if not nodeInside:
# 				leftmostNodes.append(n)

# 	# sorting by verticality FROM BOTTOM; may not be necessary depending on the setup
# 	leftmostNodes = sorted(leftmostNodes, key=lambda node: node.y)


# 	# check if there is any jump between paths
# 	# if jumps across between open paths (i.e. jump to the edge of path)
# 	# if jumps mid another path
# 	nodesToAdd = []
# 	for i, n in enumerate(leftmostNodes):  # checking from top to bottom
# 		if i == 0:
# 			continue
# 		prevNode = leftmostNodes[i - 1]
# 		thisPath, prevPath = n.parent, prevNode.parent
# 		if thisPath != prevPath:  # jump ocurring
# 			# log('jumping! {n.y} {prevNode.y}')
# 			# gap between paths
# 			prevPathTop = prevPath.bounds[0][1] + prevPath.bounds[1][1]
# 			thisPathBtm = thisPath.bounds[0][1]
# 			log(f'{prevPathTop} {thisPathBtm}')

# 			if prevPathTop < thisPathBtm:  # open gap
# 				# log('\topen or crossing?')
# 				if n.x <= prevNode.x:  # current node is more right (inside)
# 					nodesToAdd.append((i, NSPoint(prevNode.x, n.y)))
# 				else:
# 					nodesToAdd.append((i, NSPoint(n.x, prevNode.y)))

# 			elif prevPathTop >= thisPathBtm:  # overlapping and touching
# 				# log('\toverlapping')

# 				segCandidates = (
# 					# new node among the previous path
# 					(prevNode, prevNode.prevNode, n),
# 					(prevNode, prevNode.nextNode, n),
# 					# new node among the current path
# 					(n, n.prevNode, prevNode),
# 					(n, n.nextNode, prevNode))
# 				for seg in segCandidates:
# 					if segmentOverlapCheck(seg):
# 						#log(f'good one {seg}')
# 						newX = x_at_nodeYPos(seg[0], seg[1], seg[2])
# 						if newX is not None:
# 							nodesToAdd.append((i, NSPoint(newX, seg[2].y)))
# 						break


# 	for n in reversed(nodesToAdd):
# 		index, node = n
# 		leftmostNodes.insert(index, node)

# 	bp = NSBezierPath.alloc().init()
# 	bp.moveToPoint_((leftmostNodes[0].x, leftmostNodes[0].y))
# 	for n in leftmostNodes[1:]:
# 		bp.lineToPoint_((n.x, n.y))

# 	return bp

# Called from outside; returns the singular bubble line (ideally)
def getFinalBubble(layer, isLeft=True) -> NSBezierPath:
	# look for the bubble information for all components
	bubbleAttributes = gatherBubbleInfo(layer, isLeft=isLeft)
	# layerAttributes = (l, theTransform, children, refers, depth)

	if bubbleAttributes:
		bp = buildBubble(theAttributes=bubbleAttributes, isLeft=isLeft, bubblePath=None, inheritedTransforms=[])
		# buildBubble contains multiple lines; need to get a single line
		# getSingleBubbleWall()
		if isLeft is False:  # on the right, move bubble
			transform = NSAffineTransform.transform()
			transform.translateXBy_yBy_(layer.width, 0)   # move by dx horizontally
			bp.transformUsingAffineTransform_(transform)
		return bp
	return None

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
	# return bubblePath




def x_at_y(p0, p1, y):
	if p1.y == p0.y:
		t = y - p0.y
	else:
		t = (y - p0.y) / (p1.y - p0.y)
	return p0.x + t * (p1.x - p0.x)

def getKernValue(bubblePathL: NSBezierPath, bubblePathR: NSBezierPath, widthL: int, debug=False) -> float:
	try:
		# make iterable for both lines
		lineA = []
		for i in range(bubblePathL.elementCount()):
			element = bubblePathL.elementAtIndex_associatedPoints_(i) # tuple of node type and node(s)
			# elements = (nodeType, (point, point... up to 3 when it's a curve))
			# lineA.append(element[1][0])
			lineA.append(NSPoint(element[1][0].x-widthL, element[1][0].y))

		lineB = []
		for i in range(bubblePathR.elementCount()):
			element = bubblePathR.elementAtIndex_associatedPoints_(i) # tuple of node type and node(s)
			lineB.append(element[1][0])
			# lineB.append(NSPoint(element[1][0].x, element[1][0].y))
		
		if debug:
			log(f'lineA: {lineA}')
			log(f'lineB: {lineB}')

		i = j = 0
		# min_dist = float("inf")
		distances = []

		while i < len(lineA) - 1 and j < len(lineB) - 1:
			a0, a1 = lineA[i], lineA[i + 1]
			b0, b1 = lineB[j], lineB[j + 1]

			# y-span of lineA and lineB segments
			y_start = max(a0.y, b0.y)
			y_end   = min(a1.y, b1.y)

			if y_start <= y_end:
				# evaluate distance at each segment's endpoints and at the intersection point if segments cross	
				for y in (y_start, y_end):
					xa = x_at_y(a0, a1, y)
					xb = x_at_y(b0, b1, y)
					# min_dist = min(min_dist, abs(xb - xa))
					distances.append(xb - xa)

			# advance the segment that ends first
			if a1.y < b1.y:
				i += 1
			else:
				j += 1
			# if debug:
				# log(f'i={i} j={j} min_dist={min_dist}')

		if debug:
			log(distances)
			
		# return min_dist
		return min(distances)
	except:
		log(f'getKernValue error: {traceback.format_exc()}', error=True)
		return float("inf")  # if error occurs, return infinite kern value to trigger fail-safe


# KERN GENERATION LOGIC

# 　function that rounds up the given number to nearest 10, used for applying minimal kernValue
# I use this because kern value may be negative.
def roundup(givenNumber):
	return int(ceil(givenNumber / 10.0)) * 10


def kernOpenType(presetName: str, selectedLayersOnly: bool):
	try:
		f = Glyphs.font
		f.disableUpdateInterface()
		m = f.selectedFontMaster

		# build pairs list
		presetsDic = Glyphs.defaults["com.Tosche.BubbleKern.presetsDic"]
		preset = presetsDic[presetName] # preset for use
		pairsList = []
		for perm in preset: # build pairsList
			glyphsL = perm[0].split()
			glyphsR = perm[1].split()
			pairsList.extend([(L, R) for L in glyphsL for R in glyphsR if f.glyphs[L] and f.glyphs[R]])
			if bool(perm[2]):
				pairsList.extend([(R, L) for L in glyphsL for R in glyphsR if f.glyphs[L] and f.glyphs[R]])
		pairsList = set(pairsList) # remove duplicates

		if selectedLayersOnly: # reduce pairList size when selected glyphs only
			# what if glyphs are refered to outside this list?
			selectedGlyphNames = [s.parent.name for s in f.selectedLayers]
			pairsList = {pair for pair in pairsList for gName in selectedGlyphNames if gName in pair} # making set

		charsToUse = {glyph for pair in pairsList for glyph in pair} # set comprehension
		bubblesDic = {} # list of bubbles used
		#  bubblesDic > glyph.name > LB > height : value
		# 							RB > height : value
		for gn in charsToUse:
			g = f.glyphs[gn]
			if g is None:
				continue
			layer = g.layers[m.id]
			bubblesDic[gn] = {}
			# referred glyphs are all flattened ...
			bubblesDic[gn]["LB"] = getFinalBubble( layer, isLeft = True )
			bubblesDic[gn]["RB"] = getFinalBubble( layer, isLeft = False )
		
		pairsCount = len(pairsList)
		# print('pairsCount', pairsCount)
		# print(bubblesDic)
		previousProgress = 0
		for i, pair in enumerate(pairsList):
			# for progress bar update
			currentProgress = round(100*i/pairsCount)
			if currentProgress > previousProgress:
				previousProgress = currentProgress
				yield currentProgress

			left, right = pair # glyph names
			# I think bubblesDic is already cleared?
			# if left not in bubblesDic or right not in bubblesDic:
			# 	continue

			widthL = f.glyphs[left].layers[m.id].width
			# no more than half of the narrower glyph
			maxKern = ( min(widthL, f.glyphs[right].layers[m.id].width,) / 2 - 1 )

			# figure out the kern value here
			# log(f'{type(bubblesDic[left]["RB"])} {type(bubblesDic[right]["LB"])} {type(widthL)}')

			debug = True if left == 'f' and right == 'u' else False  # for debug
			# debug = True if right =='u' else False  # for debug
			kernValue = round(getKernValue(bubblesDic[left]['RB'], bubblesDic[right]['LB'], int(widthL), debug=debug))
		
			if debug:
				log(f'Left =  {left}:', type(bubblesDic[left]['RB']))
				log(f'Right = {right}:', type(bubblesDic[right]['LB']))
				log(f'kernValue: {kernValue}')

			if kernValue < maxKern:
				if abs(kernValue) >= 10:  # kerned as is if larger than 10 units
					f.setKerningForPair(m.id, left, right, -kernValue)
				elif 8 <= abs(kernValue) < 10:  # kerned 10 units if it's between 7 and 10
					f.setKerningForPair(m.id, left, right, -roundup(kernValue))
			else:  # activates fail-safe by using maxKern if kernValue is too large or infinite
				f.setKerningForPair(m.id, left, right, -int(maxKern))

			# THE END
			f.enableUpdateInterface()
	except:
		log(f'kernOpenType error: {traceback.format_exc()}', error=True)