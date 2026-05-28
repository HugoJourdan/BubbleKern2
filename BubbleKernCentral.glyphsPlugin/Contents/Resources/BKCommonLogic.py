# encoding: utf-8

from GlyphsApp import Glyphs, GSLayer, GSAlignmentDisable
import traceback
from Foundation import NSAffineTransform, NSPoint
from AppKit import NSBezierPath, NSTextField
from Cocoa import NSAlert, NSAlertStyleCritical
from dataclasses import dataclass, field
from typing import Optional
# from math import ceil, radians, tan
import math

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
		italicAngle = math.radians(90 - italicAngle)
		return x - (y - xHeight / 2) / math.tan(italicAngle)
	else:
		return x

# called from getFinalBubble()
# def collectBubbleShapes(layer, theTransform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0) -> layerAttributes | None:
def isReferenceValid(layer, side) -> bool:
	# RETURNS True IF REFERENCE EXISTS IN FONT AND CAUSES NO CIRCULAR CHAIN.
	# side IS EITHER 'L' OR 'R'.
	try:
		gName = layer.userData.get('BubbleKernRefer' + side)
		if not gName:
			return True  # no reference is always valid
		font = layer.font()
		if not font:
			return False
		mId = layer.associatedMasterId
		visited = {layer.parent.name}
		current_name = gName
		while current_name:
			if current_name in visited:
				return False  # circular reference
			if not font.glyphs[current_name]:
				return False  # glyph does not exist in font
			visited.add(current_name)
			current_layer = font.glyphs[current_name].layers[mId]
			current_name = current_layer.userData.get('BubbleKernRefer' + side) or None
		return True
	except:
		log(f'isReferenceValid error: {traceback.format_exc()}', error=True)
		return False

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
			if isReferenceValid(layer, 'L' if isLeft else 'R'):  # skip invalid/circular references
				refers = True
				gName = layer.userData[side]
				# get the gName layer's bubble info
				referredLayer = f.glyphs[gName].layers[layer.associatedMasterId]
				children.append(gatherBubbleInfo(referredLayer, defaultTransform, False, depth + 1))
		else:  # reference doesn't exist; look for components
			if len(layer.paths) == 0 and len(layer.components) > 0:
			# components only (ignore components in mixed situation)
				for c in layer.components:  # if reference doesn't exist, chase down components
					# add only when automatic alignment is on and alignment is not disabled
					if c.automaticAlignment == False or c.alignment != GSAlignmentDisable:
						continue
					if c.transform != defaultTransform:
						continue
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
	except ValueError:
		# log(f'getKernValue error: {traceback.format_exc()}', error=True)
		return float("inf")  # if error occurs, return infinite kern value to trigger fail-safe


# KERN GENERATION LOGIC

# 　function that rounds up the given number to nearest 10, used for applying minimal kernValue
# I use this because kern value may be negative.
def roundup(givenNumber):
	return int(math.ceil(givenNumber / 10.0)) * 10


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
			maxKern = ( min(widthL, f.glyphs[right].layers[m.id].width,) / 2 )

			# figure out the kern value here
			# log(f'{type(bubblesDic[left]["RB"])} {type(bubblesDic[right]["LB"])} {type(widthL)}')

			# debug = True if left == 'f' and right == 'u' else False  # for debug
			debug = False
			# log(f'Calculating kern for {left} and {right}...')
			# log()
			rawKern = getKernValue(bubblesDic[left]['RB'], bubblesDic[right]['LB'], int(widthL), debug=debug)
			kernValue = round(rawKern) if not math.isinf(rawKern) else rawKern
		
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





# BBLH TABLE EXPORT LOGIC (Written entirely by AI so far)

"""
Custom BBLH Table for FontTools
Stores glyph names with up to two sets of node coordinates.
Format: version (>H), glyphCount (>I), then for each glyph:
  presence (>B), if present: n1 (>H), coords1 (n1 x >ii), n2 (>H), coords2 (n2 x >ii)
"""

# from fontTools.ttLib import TTFont
# from fontTools.ttLib.tables import DefaultTable
# import io
# from struct import pack, unpack


# class table_B_B_L_H(DefaultTable.DefaultTable):
# 	"""Custom BBLH table class for FontTools."""
	
# 	def __init__(self, tag=None):
# 		super().__init__(tag)
# 		self.glyphs = {}  # {glyph_name: ((coords_set1), (coords_set2))}
	
# 	def compile(self, ttFont):
# 		"""Compile the BBLH table to binary data."""
# 		data = io.BytesIO()
		
# 		# Write version (uint16)
# 		data.write(pack('>H', 1))  # Version 1.0
		
# 		# Get glyph order from font
# 		glyphOrder = ttFont.getGlyphOrder()
		
# 		# Write number of glyphs (uint32)
# 		data.write(pack('>I', len(glyphOrder)))
		
# 		# Write glyph entries in glyph order
# 		for glyph_name in glyphOrder:
# 			if glyph_name not in self.glyphs:
# 				# No data for this glyph
# 				data.write(pack('>B', 0))  # presence flag = 0
# 			else:
# 				# Has data
# 				data.write(pack('>B', 1))  # presence flag = 1
				
# 				coord_set1, coord_set2 = self.glyphs[glyph_name]
				
# 				# Write set1 count and coordinates
# 				data.write(pack('>H', len(coord_set1)))
# 				for x, y in coord_set1:
# 					data.write(pack('>ii', x, y))  # Signed 32-bit integers
				
# 				# Write set2 count and coordinates
# 				data.write(pack('>H', len(coord_set2)))
# 				for x, y in coord_set2:
# 					data.write(pack('>ii', x, y))
		
# 		return data.getvalue()
	
# 	def decompile(self, data, ttFont):
# 		"""Decompile binary data into the BBLH table."""
# 		reader = io.BytesIO(data)
# 		glyphOrder = ttFont.getGlyphOrder()
		
# 		# Read version
# 		version_bytes = reader.read(2)
# 		if len(version_bytes) < 2:
# 			return
# 		version = unpack('>H', version_bytes)[0]
		
# 		# Read number of glyphs
# 		count_bytes = reader.read(4)
# 		if len(count_bytes) < 4:
# 			return
# 		glyph_count = unpack('>I', count_bytes)[0]
		
# 		self.glyphs = {}
		
# 		for glyph_idx in range(min(glyph_count, len(glyphOrder))):
# 			# Read presence flag
# 			presence_bytes = reader.read(1)
# 			if len(presence_bytes) < 1:
# 				break
# 			presence = unpack('>B', presence_bytes)[0]
			
# 			if presence == 0:
# 				# No data for this glyph
# 				continue
			
# 			glyph_name = glyphOrder[glyph_idx]
			
# 			# Read set1 count and coordinates
# 			n1_bytes = reader.read(2)
# 			if len(n1_bytes) < 2:
# 				break
# 			n1 = unpack('>H', n1_bytes)[0]
			
# 			coord_set1 = []
# 			for _ in range(n1):
# 				coord_bytes = reader.read(8)
# 				if len(coord_bytes) < 8:
# 					break
# 				x, y = unpack('>ii', coord_bytes)
# 				coord_set1.append((x, y))
			
# 			# Read set2 count and coordinates
# 			n2_bytes = reader.read(2)
# 			if len(n2_bytes) < 2:
# 				break
# 			n2 = unpack('>H', n2_bytes)[0]
			
# 			coord_set2 = []
# 			for _ in range(n2):
# 				coord_bytes = reader.read(8)
# 				if len(coord_bytes) < 8:
# 					break
# 				x, y = unpack('>ii', coord_bytes)
# 				coord_set2.append((x, y))
			
# 			self.glyphs[glyph_name] = (tuple(coord_set1), tuple(coord_set2))
	
# 	def toXML(self, writer, ttFont):
# 		"""Convert BBLH table to XML."""
# 		writer.begintag('BBLH')
# 		writer.newline()
		
# 		glyphOrder = ttFont.getGlyphOrder()
		
# 		for glyph_name in glyphOrder:
# 			if glyph_name not in self.glyphs:
# 				continue
			
# 			set1, set2 = self.glyphs[glyph_name]
# 			writer.simpletag('glyph', name=glyph_name)
# 			writer.newline()
			
# 			# Write first set
# 			writer.begintag('set', index='1')
# 			writer.newline()
# 			for x, y in set1:
# 				writer.simpletag('coord', x=x, y=y)
# 				writer.newline()
# 			writer.endtag('set')
# 			writer.newline()
			
# 			# Write second set
# 			writer.begintag('set', index='2')
# 			writer.newline()
# 			for x, y in set2:
# 				writer.simpletag('coord', x=x, y=y)
# 				writer.newline()
# 			writer.endtag('set')
# 			writer.newline()
			
# 			writer.endtag('glyph')
# 			writer.newline()
		
# 		writer.endtag('BBLH')
# 		writer.newline()
	
# 	def fromXML(self, name, attrs, parent):
# 		"""Parse BBLH table from XML."""
# 		if name == 'BBLH':
# 			self.glyphs = {}
# 		elif name == 'glyph':
# 			self._current_glyph = attrs['name']
# 			self._current_sets = [[], []]
# 		elif name == 'set':
# 			self._current_set_idx = int(attrs['index']) - 1
# 		elif name == 'coord':
# 			x = int(attrs['x'])
# 			y = int(attrs['y'])
# 			self._current_sets[self._current_set_idx].append((x, y))


def _normalize_nodes_for_export(rawNodes:NSBezierPath, isRight:bool=True, width:float=None):
	if rawNodes is None:
		return []
	
	# extract nodes from NSBezierPath
	nodesTemp = []
	for i in range(rawNodes.elementCount()):
		element = rawNodes.elementAtIndex_associatedPoints_(i) # tuple of node type and node(s)
		nodesTemp.append(element[1][0])

	# nodes = []
	# for n in nodesTemp:
	# 	xValue = int(round(n.x + width)) if isRight else int(round(n.x))
	# 	nodes.append((xValue, int(round(n.y))))

	nodes = [(int(round(n.x)), int(round(n.y))) for n in nodesTemp]

	# if not rawNodes:
	# 	return []
	# nodes = []
	# for n in rawNodes:
	# 	if len(n) >= 2: # zero or one node is wrong format; skip
	# 		xValue = int(round((n[0] + width))) if isRight else int(round(n[0]))
	# 		nodes.append((xValue, int(round(n[1]))))
	return nodes


def collectBBLHData(font=None, masterId=None) -> dict:
	"""
	Collect BubbleKern node data for a master and return it as:
	{
		"A": [[(x, y), ...], [(x, y), ...]],
		"B": [[...], [...]],
	}

	Only glyphs that have at least one bubble side are included.
	"""
	try:
		f = font

		# master_id = masterId
		# if not master_id:
		# 	selected_master = getattr(f, "selectedFontMaster", None)
		# 	master_id = selected_master.id if selected_master else None
		# if not master_id:
		# 	return {}
		# log(f'collectBBLHData called with masterId: {masterId}')
		result = {}
		for g in f.glyphs:
			try:
				layer = g.layers[masterId]
			except:
				continue
			wid = layer.width
			# maybe should improve bubble generation logic to incorporate components and references,
			# so that the exported BBLH data is more complete and accurate;
			# currently only the nodes directly on the master layer are exported,
			# which may miss some bubbles if they are built from components or references
			left_nodes = _normalize_nodes_for_export(getFinalBubble( layer, isLeft = True ), False, None)
			right_nodes = _normalize_nodes_for_export(getFinalBubble( layer, isLeft = False ), True, wid)
			# log(f'Glyph: {g.name}, left bubble: {left_nodes}, right bubble: {right_nodes}')

			# left_nodes = _normalize_nodes_for_export(layer.userData.get(nodesKeyL), False, None)
			# right_nodes = _normalize_nodes_for_export(layer.userData.get(nodesKeyR), True, wid)

			# if not left_nodes and not right_nodes:
			# 	continue

			result[g.name] = [left_nodes, right_nodes]
		
		# log(f'collectBBLHData result: {result}')
		return result
	except:
		log(f'collectBBLHData error: {traceback.format_exc()}', error=True)
		return {}



# to be run from BKKerner
# def add_bblh_table(font_path, bblh_data, output_path):
def writeFontWithBBLH(folderPath, font=None): # want to use this name later
	"""
	Add BBLH table to a font.

	bblh_data: Dict with glyph names as keys and 
				((coord_set1), (coord_set2)) as values.
				Use empty tuples () for missing coordinate sets.
	Example:
		bblh_data = {
			'A': (((0, 1), (125, 699)), ((639, 0), (501, 696))),
			'R': ((), ((412, -8), (520, 613), (520, 800))),
			'T': (((109, -16), (0, 611), (0, 800)), ((412, -8), (520, 613), (520, 800))),
		}
		add_bblh_table('your_font.ttf', bblh_data, 'your_font_with_bblh.ttf')
	"""
	try:
		from fontTools.ttLib import TTFont
		from fontTools.ttLib.tables import DefaultTable
		import io
		from struct import pack, unpack
	except ImportError:
		show_alert(
			"FontTools is required.",
			"Install it in Glyphs Python with: pip install fonttools",
			cancel=False,
		)
		return None
	
	# make a class to build BBLH table data
	class table_B_B_L_H(DefaultTable.DefaultTable):
		"""Custom BBLH table class for FontTools."""
	
		def __init__(self, tag=None):
			super().__init__(tag)
			self.glyphs = {}  # {glyph_name: ((coords_set1), (coords_set2))}
		
		def compile(self, ttFont):
			"""Compile the BBLH table to binary data."""
			data = io.BytesIO()
			
			# Write version (uint16)
			data.write(pack('>H', 1))  # Version 1.0
			
			# Get glyph order from font
			glyphOrder = ttFont.getGlyphOrder()
			
			# Write number of glyphs (uint32)
			data.write(pack('>I', len(glyphOrder)))
			
			# Write glyph entries in glyph order
			for glyph_name in glyphOrder:
				if glyph_name not in self.glyphs:
					# No data for this glyph
					data.write(pack('>B', 0))  # presence flag = 0
				else:
					# Has data
					data.write(pack('>B', 1))  # presence flag = 1
					
					coord_set1, coord_set2 = self.glyphs[glyph_name]
					
					# Write set1 count and coordinates
					data.write(pack('>H', len(coord_set1)))
					for x, y in coord_set1:
						data.write(pack('>ii', x, y))  # Signed 32-bit integers
					
					# Write set2 count and coordinates
					data.write(pack('>H', len(coord_set2)))
					for x, y in coord_set2:
						data.write(pack('>ii', x, y))
			
			return data.getvalue()
		
		def decompile(self, data, ttFont):
			"""Decompile binary data into the BBLH table."""
			reader = io.BytesIO(data)
			glyphOrder = ttFont.getGlyphOrder()
			
			# Read version
			version_bytes = reader.read(2)
			if len(version_bytes) < 2:
				return
			version = unpack('>H', version_bytes)[0]
			
			# Read number of glyphs
			count_bytes = reader.read(4)
			if len(count_bytes) < 4:
				return
			glyph_count = unpack('>I', count_bytes)[0]
			
			self.glyphs = {}
			
			for glyph_idx in range(min(glyph_count, len(glyphOrder))):
				# Read presence flag
				presence_bytes = reader.read(1)
				if len(presence_bytes) < 1:
					break
				presence = unpack('>B', presence_bytes)[0]
				
				if presence == 0:
					# No data for this glyph
					continue
				
				glyph_name = glyphOrder[glyph_idx]
				
				# Read set1 count and coordinates
				n1_bytes = reader.read(2)
				if len(n1_bytes) < 2:
					break
				n1 = unpack('>H', n1_bytes)[0]
				
				coord_set1 = []
				for _ in range(n1):
					coord_bytes = reader.read(8)
					if len(coord_bytes) < 8:
						break
					x, y = unpack('>ii', coord_bytes)
					coord_set1.append((x, y))
				
				# Read set2 count and coordinates
				n2_bytes = reader.read(2)
				if len(n2_bytes) < 2:
					break
				n2 = unpack('>H', n2_bytes)[0]
				
				coord_set2 = []
				for _ in range(n2):
					coord_bytes = reader.read(8)
					if len(coord_bytes) < 8:
						break
					x, y = unpack('>ii', coord_bytes)
					coord_set2.append((x, y))
				
				self.glyphs[glyph_name] = (tuple(coord_set1), tuple(coord_set2))
		
		def toXML(self, writer, ttFont):
			"""Convert BBLH table to XML."""
			writer.begintag('BBLH')
			writer.newline()
			
			glyphOrder = ttFont.getGlyphOrder()
			
			for glyph_name in glyphOrder:
				if glyph_name not in self.glyphs:
					continue
				
				set1, set2 = self.glyphs[glyph_name]
				writer.simpletag('glyph', name=glyph_name)
				writer.newline()
				
				# Write first set
				writer.begintag('set', index='1')
				writer.newline()
				for x, y in set1:
					writer.simpletag('coord', x=x, y=y)
					writer.newline()
				writer.endtag('set')
				writer.newline()
				
				# Write second set
				writer.begintag('set', index='2')
				writer.newline()
				for x, y in set2:
					writer.simpletag('coord', x=x, y=y)
					writer.newline()
				writer.endtag('set')
				writer.newline()
				
				writer.endtag('glyph')
				writer.newline()
			
			writer.endtag('BBLH')
			writer.newline()
		
		def fromXML(self, name, attrs, parent):
			"""Parse BBLH table from XML."""
			if name == 'BBLH':
				self.glyphs = {}
			elif name == 'glyph':
				self._current_glyph = attrs['name']
				self._current_sets = [[], []]
			elif name == 'set':
				self._current_set_idx = int(attrs['index']) - 1
			elif name == 'coord':
				x = int(attrs['x'])
				y = int(attrs['y'])
				self._current_sets[self._current_set_idx].append((x, y))

	# end of BBLH class definition

	if font is None:
		return None

	exportedPaths = []
	# for ins in font.instances:
	# 	log(f'Processing instance: {ins.name}')
	# 	if not ins.active:
	# 		log(f'Skipping inactive instance')
	# 		continue

	# 	# check if ins values are identical to master; else, need to interpolate node coordinates
	# 	useMaster = None # None or master id
	# 	for m in font.masters:
	# 		if ins.axes == m.axes:
	# 			useMaster = m.id
	# 			break
	# 			# write some logic to skip compatibility check & use master values
	# 	if useMaster == None: # individual instance
	# 		bubblesCompatible = True
	# 		bblhData = {}
	# 		for m in font.masters:
	# 			bblhData[m.id] = collectBBLHData(font=font, masterId=m.id)
	# 		masterIDs= [m.id for m in f.masters]
	# 		for g in f.glyphs:
	# 			for side in (0, 1):
	# 				nodeLens = [len(bblhData[mID][g.name][side]) for mID in masterIDs]
	# 				if len(set(nodeLens)) != 1:
	# 					bubblesCompatible = False
	# 					break
	# 			if not bubblesCompatible:
	# 				break

	# 		if not bubblesCompatible:
	# 			continue
	# 		# prepare the weight values for each axis (only used in interpolation case)
	# 		insWeightValues = [ 0 for a in range(len(font.axes)) ]





	for m in font.masters:
		# log(f'Processing master: {m.name}')
		# check for valid instance
		insFound = False
		for ins in font.instances:
			if ins.active and ins.axes == m.axes:
				insFound = True
				break
		if insFound is False:
			return None

		# gather bblh data
		bblhData = collectBBLHData(font=font, masterId=m.id)
		# log(f'Collected BBLH data for master {m.name}: {bblhData}')
		if not bblhData:
			# log("writeFontWithBBLH: no bubble data found; skipping BBLH table write.")
			return None
		
		# generate instance in the inputFontPath
		ins.generate(fontPath=folderPath)
		fontFileName = ins.lastExportedFilePath.split('/')[-1]
		outputFontPath = folderPath + '/' + fontFileName # path to the font file
		# log(f'output font path: {outputFontPath}')


		bubbledFont = TTFont(outputFontPath)
		
		# Create BBLH table
		bblh_table = table_B_B_L_H('BBLH')
		bblh_table.glyphs = bblhData
		
		# Add to font
		bubbledFont['BBLH'] = bblh_table
		
		# Save
		bubbledFont.save(outputFontPath)
		# log(f"Font saved with BBLH table to {outputFontPath}")
		exportedPaths.append(outputFontPath)
	
	log('writeFontWithBBLH completed successfully.')
	return exportedPaths














# def serializeBBLHData(bblhData, glyphOrder):
# 	"""
# 	Serialize BBLH payload to the same binary layout used by the sample OTF.

# 	Big-endian layout:
# 	  uint16 version
# 	  uint32 glyphCount
# 	  repeated glyphCount times:
# 		uint8  presence
# 		if presence != 0:
# 		  uint16 set1Count
# 		  set1Count * (int32 x, int32 y)
# 		  uint16 set2Count
# 		  set2Count * (int32 x, int32 y)
# 	"""
# 	import struct

# 	buffer = bytearray()
# 	buffer += struct.pack(">HI", 1, len(glyphOrder))

# 	for glyphName in glyphOrder:
# 		left_nodes, right_nodes = bblhData.get(glyphName, ([], []))
# 		if not left_nodes and not right_nodes:
# 			buffer += struct.pack(">B", 0)
# 			continue

# 		buffer += struct.pack(">B", 1)
# 		buffer += struct.pack(">H", len(left_nodes))
# 		for x, y in left_nodes:
# 			buffer += struct.pack(">ii", int(x), int(y))
# 		buffer += struct.pack(">H", len(right_nodes))
# 		for x, y in right_nodes:
# 			buffer += struct.pack(">ii", int(x), int(y))

# 	return bytes(buffer)


# def writeFontWithBBLH(folderPath, font=None):
# 	try:
# 		log(f'writeFontWithBBLH called with folderPath: {folderPath}')
# 		try:
# 			from fontTools import ttLib
# 		except ImportError:
# 			show_alert(
# 				"FontTools is required.",
# 				"Install it in Glyphs Python with: pip install fonttools",
# 				cancel=False,
# 			)
# 			return None

# 		if font is None:
# 			return None
# 		log(f'commencing BBLH export for font: {font.familyName}')
# 		# fonts need to be generated for all masters; need to be run multiple times for MM
# 		for m in font.masters:
# 			log(f'Processing master: {m.name}')
# 			# check for valid instance
# 			insFound = False
# 			for ins in font.instances:
# 				if ins.active and ins.axes == m.axes:
# 					insFound = True
# 					break
# 			if insFound is False:
# 				return None

# 			# gather bblh data
# 			bblhData = collectBBLHData(font=font, masterId=m.id)
# 			if not bblhData:
# 				log("writeFontWithBBLH: no bubble data found; skipping BBLH table write.")
# 				return None
			
# 			# generate instance in the inputFontPath
# 			ins.generate(fontPath=folderPath)
# 			log(f'generated font for master: {m.name} at path: {folderPath}')
# 			outputFontPath = ins.lastExportedFilePath # path to the font file
# 			log(f'output font path: {outputFontPath}')



# 			# if outputFontPath is None:
# 			# 	stem, ext = os.path.splitext(inputFontPath)
# 			# 	outputFontPath = f"{stem}_BBLH{ext}"

# 			tt = ttLib.TTFont(outputFontPath)
# 			glyphOrder = tt.getGlyphOrder()
# 			table = ttLib.newTable("BBLH")
# 			table.data = serializeBBLHData(bblhData, glyphOrder)
# 			tt["BBLH"] = table
# 			tt.save(outputFontPath)
# 			tt.close()

# 			# Verify persistence immediately to isolate table write issues.
# 			checkFont = TTFont(outputFontPath)
# 			hasBBLH = "BBLH" in checkFont
# 			if hasBBLH:
# 				payloadLen = len(checkFont["BBLH"].data)
# 				log(f"writeFontWithBBLH: wrote {len(bblhData)} glyph entries to {outputFontPath} (BBLH bytes={payloadLen})")
# 			else:
# 				log(f"writeFontWithBBLH: save completed but BBLH missing in {outputFontPath}. tables={list(checkFont.keys())}", error=True)
# 			checkFont.close()
# 			log()
# 			# return outputFontPath
# 	except:
# 		log(f'writeFontWithBBLH error: {traceback.format_exc()}', error=True)
# 		return None


# to be run from BK Tool (incomplete)
def autoBuildBubble(layer, isLeft=True):
	try:
		decomposedLayer = layer.copyDecomposedLayer()

	except:
		log(f'autoBuildBubble error (decomposing layer): {traceback.format_exc()}', error=True)
		return None
