# encoding: utf-8

from GlyphsApp import Glyphs, GSLayer, GSAlignmentDisable
import traceback
from Foundation import NSAffineTransform, NSPoint
from AppKit import NSBezierPath, NSTextField
from Cocoa import NSAlert, NSAlertStyleCritical
from dataclasses import dataclass, field

from BKSide import LEFT, RIGHT, of
from typing import Optional
import math

# THIS IS WHERE THE SHARED BACKEND CODE SHOULD BE STORED
# SUCH AS CALCULATING THE BUBBLE SHAPE, DEALING WITH INHERITED (I.E. COMPONENT) BUBBLES.

# THE KEYS THEMSELVES COME FROM THE SIDE - `LEFT.key('Nodes')`. What is left
# below is the two things a person types and the note on what the box is for,
# which are not keys.
# A SIDE THAT MIRRORS THE OTHER SIDE OF THE SAME GLYPH. STORES NOTHING BUT THE
# FLAG, SO IT CANNOT DRIFT: THE SHAPE IS RESOLVED FROM THE LIVE OTHER SIDE
# EVERY TIME IT IS ASKED FOR, INCLUDING MID-DRAG.
# WHAT A PERSON TYPES to mirror the other side. Glyphs' own metric keys spell
# "the other side of this glyph" `=|`, and a bubble is a kind of sidebearing.
MIRROR_TOKEN = '=|'
# A SIDE THAT KEEPS ITSELF. Typing this instead of a glyph name hands the side
# back to the generator: it is drawn from the outline now and drawn again
# whenever the outline moves, so it can never be left describing ink that has
# gone. Stored as a flag beside the nodes rather than in the reference, because
# the side still OWNS what it draws - it just did not draw it by hand.
AUTO_TOKEN = 'auto'
# THE LAYER'S BOUNDING BOX AS IT WAS WHEN THE BUBBLE WAS LAST WRITTEN. A BUBBLE
# IS JUST COORDINATES: REDRAW THE GLYPH AND IT STAYS WHERE IT WAS, SILENTLY,
# AND NOTHING IN THE FILE RECORDS THAT THE TWO HAVE PARTED COMPANY.
# HOW FAR THE BOX MAY MOVE BEFORE THE BUBBLE COUNTS AS STALE, IN UNITS. A NUDGE
# TO ONE NODE OF AN OUTLINE SHOULD NOT LIGHT UP THE WHOLE FONT.
STALE_TOLERANCE = 2
defaultTransform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
TempDataBubblesKey = 'bubbles'


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
	children: list["layerAttributes"] = field(default_factory=list)
	refers: bool = False
	depth: int = 0
	# THIS SIDE IS THE OTHER ONE OF THE SAME LAYER, FLIPPED. Not a list of
	# nodes but a whole wall turned round, so it is built and flipped rather
	# than read: the single child holds the side it mirrors.
	mirrored: bool = False


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
			text = inputField.stringValue().strip() # strip removes white spaces from both ends of str
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
	try:
		gName = layer.userData.get(side.key('Refer'))
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
			current_name = current_layer.userData.get(side.key('Refer')) or None
		return True
	except Exception:
		log(f'isReferenceValid error: {traceback.format_exc()}', error=True)
		return False

def isTranslationOnly(transform) -> bool:
	# (a, b, c, d, tx, ty) WITH NOTHING BUT THE MOVE IN IT.
	try:
		a, b, c, d = (float(v) for v in tuple(transform)[:4])
	except Exception:
		return False
	return a == 1.0 and b == 0.0 and c == 0.0 and d == 1.0

def isBlankWall(nodes) -> bool:
	# THE DEFAULT STRAIGHT LINE ON THE ORIGIN - what a layer carries when nobody
	# has drawn it a bubble. It says nothing about a shape, and on a composite it
	# says it LOUDLY: the merge keeps whatever reaches furthest into the
	# whitespace, and a line on the origin beats every wall its components have.
	try:
		return len(nodes) <= 2 and all(int(round(n[0])) == 0 for n in nodes)
	except Exception:
		return False

def mergeableComposite(layer) -> bool:
	# A LAYER WHOSE COMPONENTS CAN SPEAK FOR IT. Every one of them has to be
	# aligned and merely moved: one component left out is a piece of ink with no
	# wall in front of it, which is worse than not merging at all. Stricter than
	# the per-component test in gatherBubbleInfo on purpose - that one salvages
	# what it can from a layer already merging, this one decides whether to leave
	# a layer with no wall of its own.
	try:
		if len(layer.paths) or not len(layer.components):
			return False
		for c in layer.components:
			if c.automaticAlignment == False or c.alignment == GSAlignmentDisable:
				return False
			if not isTranslationOnly(c.transform):
				return False
		return True
	except Exception:
		log(f'mergeableComposite error: {traceback.format_exc()}', error=True)
		return False

def resolvesToBlank(attributes, isLeft) -> bool:
	# TRUE WHEN A CONTRIBUTOR RESOLVES TO NOTHING BUT THE DEFAULT LINE, which
	# is what a layer carries when nobody has drawn it a wall. Harmless where
	# it sits and not harmless anywhere else: moved onto a composite it becomes
	# a wall standing at the COMPONENT'S origin - outside the glyph when the
	# component is moved left - and the union keeps whatever reaches furthest
	# out.
	# ponytail: reads the STORED nodes, so a component being dragged in another
	# tab counts as blank until the drag is saved.
	try:
		if attributes is None:
			return True
		if attributes.mirrored:
			# THE CHILD IS THE OTHER SIDE, so that is the side to ask about.
			return all(resolvesToBlank(c, not isLeft) for c in attributes.children)
		if attributes.children:
			return all(resolvesToBlank(c, isLeft) for c in attributes.children)
		if attributes.refers:
			return True  # borrows its shape, and had nothing to borrow from
		nodes = attributes.layer.userData[of(isLeft).key('Nodes')]
		return not nodes or isBlankWall(nodes)
	except Exception:
		log(f'resolvesToBlank error: {traceback.format_exc()}', error=True)
		return False

def gatherBubbleInfo(layer, theTransform=defaultTransform, refers=False, depth=0, isLeft=True) -> layerAttributes | None:
	# FOR GETTING ACCUMULATED ATTRIBUTES FROM NESTED BUBBLES.
	# INPUT LAYER, TRANSFORM, AND CURRENT BUBBLE PURSUIT LEVEL.
	# RETURNS A LAYER ATTRIBUTES INSTANCE.
	try:
		# A COMPONENT CAN POINT AT A GLYPH THAT IS NOT THERE, and Glyphs hands
		# back a layer with no font and no glyph behind it rather than nothing.
		if layer is None or layer.parent is None:
			return None
		if isMirrored(layer, isLeft):
			# RESOLVED HERE, NOT ONLY IN getFinalBubble. A mirrored side stores
			# nothing but the flag, so a composite reading its components for
			# nodes would otherwise find none. See CLAUDE.md.
			other = gatherBubbleInfo(layer, defaultTransform, False, depth,
				not isLeft)
			if other is None:
				return None
			return layerAttributes(layer, theTransform, [other], True, depth, True)
		f = layer.font()
		m = layer.associatedFontMaster()

		children = []  # info for components in the layer
		fromComponents = False  # ...as opposed to from a reference
		# NAMED FOR WHAT IT IS. This was called `side` and held a KEY.
		referKey = of(isLeft).key('Refer')
		if layer.userData[referKey]:  # if reference exists
			if isReferenceValid(layer, of(isLeft)):  # skip invalid/circular references
				refers = True
				gName = layer.userData[referKey]
				# get the gName layer's bubble info
				referredLayer = f.glyphs[gName].layers[layer.associatedMasterId]
				# THE SAME SIDE, ALL THE WAY DOWN. Left out, `isLeft` falls back to
				# its default and every chain is followed along the LEFT. See
				# CLAUDE.md.
				children.append(gatherBubbleInfo(referredLayer, defaultTransform,
					False, depth + 1, isLeft))
		else:  # reference doesn't exist; look for components
			if len(layer.paths) == 0 and len(layer.components) > 0:
			# components only (ignore components in mixed situation)
				for c in layer.components:  # if reference doesn't exist, chase down components
					# ADD ONLY WHEN AUTOMATIC ALIGNMENT IS ON AND ALIGNMENT IS NOT
					# DISABLED. An ordinary aligned component reports 0 against a
					# GSAlignmentDisable of -1, so `!=` is true for every component
					# in every font - do not "simplify" this. See CLAUDE.md.
					if c.automaticAlignment == False or c.alignment == GSAlignmentDisable:
						continue
					# A MOVED COMPONENT IS STILL ITS OWN SHAPE, and buildBubble
					# carries the transform down already, so a translation is
					# nothing to guard against - an accent is translated by
					# definition, and demanding the identity dropped every one.
					# SCALED, ROTATED OR MIRRORED is a different matter: mirror a
					# left wall and it describes a right one. Those stay out.
					if not isTranslationOnly(c.transform):
						continue
					fromComponents = True
					children.append(gatherBubbleInfo(c.componentLayer, c.transform,
						False, depth + 1, isLeft))

		# WHAT IS LEFT TO INHERIT FROM. A child that answered None has no wall and
		# nothing to borrow, and one that resolves to the default line has nothing
		# to say either. With none of them solid the layer inherits NOTHING and
		# falls back to its own line below - better a line on the origin than a
		# component's origin dragged out into the whitespace.
		children = [c for c in children
			if c is not None and not resolvesToBlank(c, isLeft)]
		for l in layer.parent.layers:  # make sure to find master layer
			if l.isMasterLayer and l.associatedFontMaster() == m:
				break
		nodesKey = of(isLeft).key('Nodes')
		ownNodes = l.userData[nodesKey] if nodesKey in l.userData else None
		if ownNodes is not None and len(ownNodes) > 0:  # bubble nodes exist
			# A COMPOSITE WITH COMPONENTS TO MERGE IGNORES ITS OWN DEFAULT LINE.
			# `refers` is how buildBubble is told a layer borrows its shape
			# instead of drawing one, and that is precisely what this layer does.
			# Every composite in an existing file carries that line - it is
			# stamped on activation - so without this the merge stays invisible.
			if children and isBlankWall(ownNodes):
				return layerAttributes(l, theTransform, children, True, depth)
			# A WALL OF ITS OWN REPLACES THE MERGE, IT DOES NOT JOIN IT. The union
			# keeps whatever reaches furthest out, so a merged composite could be
			# pushed outward by hand but never inward: drag a node in and a
			# component's wall was still standing behind it. Auto-generate leaves a
			# mergeable composite no nodes at all, so nodes here mean somebody drew
			# them, and drawn beats inherited.
			if fromComponents:
				return layerAttributes(l, theTransform, [], refers, depth)
			return layerAttributes(l, theTransform, children, refers, depth)
		if children:
			# A SIDE THAT BORROWS ITS SHAPE OWNS NO NODES OF ITS OWN, AND THAT IS
			# THE POINT: A REFERRED SIDE READS THE OTHER GLYPH'S WALL AND A
			# COMPOSITE READS ITS COMPONENTS'. REQUIRING NODES HERE SENDS EVERY
			# SUCH SIDE TO None, AND THE KERNER TO ITS FAIL-SAFE.
			# AND `refers` SAYS SO, WHATEVER PUT THE CHILDREN THERE - left False,
			# buildBubble finds the CACHE and unions the merge with its own last
			# answer. See CLAUDE.md.
			return layerAttributes(l, theTransform, children, True, depth)
		# no bubble here and nothing to borrow from
		return None
	except Exception:
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

		if theAttributes.mirrored:
			# A FLIP OF A WHOLE WALL, NOT OF A LIST OF NODES. Built on its own
			# and merged to one line first, because the flip walks a path as a
			# single polyline - handed two subpaths it would join them end to
			# end. Flipped about THIS layer's advance, and only then moved to
			# where this layer sits: the two do not commute.
			inner = NSBezierPath.alloc().init()
			for child in theAttributes.children:
				buildBubble(child, not isLeft, inner, [])
			if inner.elementCount():
				inner = unionSubpaths(inner, not isLeft)
				inner = mirrorBubblePath(inner, theAttributes.layer)
				for t in currentTransforms:
					trans = NSAffineTransform()
					trans.setTransformStruct_(t)
					inner.transformUsingAffineTransform_(trans)
				bubblePath.appendBezierPath_(inner)
			return bubblePath
		if theAttributes.children:  # IF THERE ARE REFERENCES OR COMPONENTS
			for child in theAttributes.children:
				buildBubble(child, isLeft, bubblePath, currentTransforms)
		# else:
			# log(f'{indent}reference/components not found in {theAttributes.layer.parent.name}')

		if theAttributes.refers is False:  # if path or component; no referred glyphs
			bubbleLayer = theAttributes.layer  # THE BUBBLE
			nodesKey = of(isLeft).key('Nodes')
			if not bubbleLayer.tempData.get(TempDataBubblesKey) and not bubbleLayer.userData[nodesKey]:
				return bubblePath  # a composite with no bubble of its own: the components are it
			m = bubbleLayer.associatedFontMaster()
			italicAngle = -m.italicAngle if m else 0
			localPath = NSBezierPath.alloc().init()
			
			if isLeft:
				try:  # try loading from tempData first
					nodes = bubbleLayer.tempData['bubbles']['nodesL']
					nodes = [(n.x, n.y) for n in sorted(nodes, key=lambda node: node.y)]  # SORT NODES BY HEIGHT
					# if loaded from tempData, the nodes ma not be in height order yet
					# (particularly while dragging)
				except Exception:
					rawNodes = bubbleLayer.userData[LEFT.key('Nodes')]
					nodes = [(tempToUserNodeX(n[0], n[1], italicAngle, m.xHeight), n[1]) for n in rawNodes]
			else:
				# A RIGHT WALL IS STORED FROM ITS OWN LAYER'S RIGHT EDGE, so it
				# is made absolute HERE, against the width of the layer it was
				# DRAWN on - not the one being built. See CLAUDE.md.
				try:
					nodes = bubbleLayer.tempData['bubbles']['nodesR']
					nodes = [(n.x, n.y) for n in sorted(nodes, key=lambda node: node.y)]  # SORT NODES BY HEIGHT
					# TEMPDATA'S NODE POS ALREADY INCLUDES THE WIDTH
				except Exception:
					rawNodes = bubbleLayer.userData[RIGHT.key('Nodes')]
					nodes = [(tempToUserNodeX(n[0], n[1], italicAngle, m.xHeight) + bubbleLayer.width, n[1]) for n in rawNodes]

			for i, n in enumerate(nodes):
				if i == 0:  # if first node
					localPath.moveToPoint_(NSPoint(n[0], n[1]))
				else:
					localPath.lineToPoint_(NSPoint(n[0], n[1]))

			# IN PLACE. `transformBezierPath:` RETURNS A TRANSFORMED COPY and
			# leaves its argument alone, so discarding the return throws the move
			# away. See CLAUDE.md.
			for t in currentTransforms:
				trans = NSAffineTransform()
				trans.setTransformStruct_(t)
				localPath.transformUsingAffineTransform_(trans)

			bubblePath.appendBezierPath_(localPath)
		# else:
		# 	log(f'{indent}bubble paths not found in {theAttributes.layer.parent.name}')
		# log(f'{indent}returning path from {theAttributes.layer.parent.name}: {bubblePath}')

	except Exception:
		log(f'buildBubble error: {traceback.format_exc()}', error=True)

	return bubblePath

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



# 			elif prevPathTop >= thisPathBtm:  # overlapping and touching
# 				# log('\toverlapping')


# Called from outside; returns the singular bubble line (ideally)
def layerBox(layer):
	# THE LAYER'S BOX AS FOUR INTS, WHICH IS WHAT GOES IN userData.
	bounds = layer.bounds
	return [int(round(bounds.origin.x)), int(round(bounds.origin.y)),
	        int(round(bounds.size.width)), int(round(bounds.size.height))]

def recordBox(layer, side):
	# CALLED WHENEVER A SIDE'S OWN NODES ARE WRITTEN. THE ADVANCE GOES IN TOO,
	# BECAUSE TELLING AN LSB CHANGE FROM AN RSB CHANGE NEEDS BOTH: MOVING THE
	# INK IS ONE, MOVING THE ADVANCE IS THE OTHER, AND AN LSB CHANGE DOES BOTH.
	layer.userData[side.key('Box')] = layerBox(layer) + [int(round(layer.width))]

def spacingShift(layer, side):
	# HOW THE SPACING HAS MOVED SINCE THIS SIDE WAS RECORDED. -> (dxInk, dWidth)
	# OR None WHEN THERE IS NOTHING TO COMPARE, OR WHEN THE INK CHANGED SIZE -
	# THAT IS A REDRAWN GLYPH, WHICH IS STALENESS AND NOT A SPACING MOVE.
	try:
		stored = layer.userData[side.key('Box')]
		if not stored or len(stored) < 5:
			return None
		box = layerBox(layer)
		# SPACING MOVES INK SIDEWAYS AND NOTHING ELSE. A BOX THAT CHANGED SIZE,
		# OR MOVED VERTICALLY, IS A REDRAWN GLYPH - AND MUST FALL THROUGH TO
		# STALENESS RATHER THAN BE QUIETLY ACCEPTED HERE, WHICH IS WHAT WOULD
		# HAPPEN IF WE REFRESHED THE RECORD FOR IT.
		for index in (1, 2, 3):  # y, width, height
			if abs(int(stored[index]) - box[index]) > STALE_TOLERANCE:
				return None
		return (box[0] - int(stored[0]), int(round(layer.width)) - int(stored[4]))
	except Exception:
		log(f'spacingShift error: {traceback.format_exc()}', error=True)
		return None

def shiftBubbleForSpacing(layer, side) -> bool:
	# MOVE A SIDE'S NODES SO THEY KEEP DESCRIBING THE SAME SHAPE AFTER A
	# SIDEBEARING CHANGE. -> True IF ANYTHING MOVED.
	#
	# A LEFT NODE IS STORED FROM THE ORIGIN, SO IT FOLLOWS THE INK: dxInk.
	# A RIGHT NODE IS STORED FROM THE ADVANCE, SO IT FOLLOWS THE INK ONLY BY
	# WHATEVER THE ADVANCE DID NOT ALREADY DO FOR IT: dxInk - dWidth. An LSB
	# CHANGE MOVES BOTH BY THE SAME AMOUNT AND THE RIGHT SIDE NEEDS NOTHING; AN
	# RSB CHANGE MOVES ONLY THE ADVANCE AND THE LEFT SIDE NEEDS NOTHING.
	#
	# NODES SITTING ON THE SIDEBEARING ITSELF STAY THERE. THEY SAY "THE SPACING
	# ALONE GOVERNS HERE", AND THAT SENTENCE IS STILL TRUE - AND STILL MEANT -
	# AFTER THE SPACING CHANGES.
	try:
		shift = spacingShift(layer, side)
		if shift is None:
			return False
		nodes = layer.userData[side.key('Nodes')]
		if not nodes:
			return False
		dxInk, dWidth = shift
		delta = dxInk if side.isLeft else dxInk - dWidth
		if delta == 0:
			recordBox(layer, side)  # nothing to move, but keep the record current
			return False
		moved = []
		for node in nodes:
			x, y = int(node[0]), int(node[1])
			if x != 0:
				x += delta
				# THE SAME RULE THE GENERATOR OBEYS: NEVER OUTSIDE THE ADVANCE.
				x = max(0, x) if side.isLeft else min(0, x)
			moved.append((x, y))
		layer.userData[side.key('Nodes')] = moved
		recordBox(layer, side)
		return True
	except Exception:
		log(f'shiftBubbleForSpacing error: {traceback.format_exc()}', error=True)
		return False

def isStale(layer, isLeft) -> bool:
	# TRUE IF THE OUTLINE HAS MOVED SINCE THIS SIDE WAS DRAWN.
	# A SIDE THAT OWNS NO NODES - REFERRED, SYNCED, INHERITED - CANNOT BE STALE:
	# IT IS RESOLVED FRESH EVERY TIME, AND THE GLYPH IT COMES FROM CARRIES ITS
	# OWN FLAG. NEITHER CAN ONE DRAWN BEFORE THIS FIELD EXISTED, SINCE THERE IS
	# NOTHING TO COMPARE AGAINST AND GUESSING WOULD CRY WOLF ON EVERY OLD FILE.
	try:
		side = of(isLeft)
		if not layer.userData[side.key('Nodes')]:
			return False
		stored = layer.userData[side.key('Box')]
		if not stored or len(stored) < 4:
			return False
		return any(abs(int(a) - b) > STALE_TOLERANCE for a, b in zip(stored[:4], layerBox(layer)))
	except Exception:
		log(f'isStale error: {traceback.format_exc()}', error=True)
		return False

# MIRROR A WALL TO THE OTHER SIDE OF THE SAME GLYPH.
# THE FLIP IS IN UPRIGHT SPACE, NOT ON THE CANVAS: A SHEAR AND A MIRROR DO NOT
# COMMUTE, SO FLIPPING AN ITALIC'S SLANTED COORDINATES WOULD LEAN THE COPY THE
# WRONG WAY. UNSHEAR, FLIP ABOUT THE MIDDLE OF THE ADVANCE, RESHEAR.
def mirrorBubblePath(bubblePath, layer) -> NSBezierPath:
	try:
		m = layer.associatedFontMaster()
		angle, xHeight = m.italicAngle, m.xHeight
		mirrored = NSBezierPath.alloc().init()
		for i in range(bubblePath.elementCount()):
			point = bubblePath.elementAtIndex_associatedPoints_(i)[1][0]
			upright = tempToUserNodeX(point.x, point.y, angle, xHeight)
			flipped = layer.width - upright
			x = tempToUserNodeX(flipped, point.y, -angle, xHeight)
			if i == 0:
				mirrored.moveToPoint_(NSPoint(x, point.y))
			else:
				mirrored.lineToPoint_(NSPoint(x, point.y))
		return mirrored
	except Exception:
		log(f'mirrorBubblePath error: {traceback.format_exc()}', error=True)
		return bubblePath

def isAuto(layer, isLeft) -> bool:
	# A SIDE ASKED TO KEEP ITSELF UP TO DATE.
	return bool(layer.userData[of(isLeft).key('Auto')])

def needsGenerating(layer, isLeft) -> bool:
	# TRUE WHEN A SIDE SHOULD BE DRAWN AGAIN FROM THE OUTLINE.
	# STALENESS COVERS EVERY SIDE THAT OWNS NODES; AN `auto` SIDE ALSO COVERS
	# THE CASE STALENESS CANNOT SEE - NOTHING DRAWN YET, OR DRAWN BEFORE ANY BOX
	# WAS RECORDED - SO ASKING FOR ONE PRODUCES ONE. IT CONVERGES EITHER WAY:
	# writeBubble RECORDS THE BOX, AND THE NEXT PASS FINDS NOTHING TO DO.
	if isStale(layer, isLeft):
		return True
	if not isAuto(layer, isLeft):
		return False
	side = of(isLeft)
	# A COMPOSITE LEFT TO ITS COMPONENTS HAS NO WALL BY DESIGN. Asking for one
	# here stamps it back on at the next interface update, and the merge that
	# clearing the nodes bought lasts exactly until somebody looks at it.
	if mergeableComposite(layer) and not layer.userData[side.key('Nodes')]:
		return False
	return not (layer.userData[side.key('Nodes')]
			and layer.userData[side.key('Box')])

def isMirrored(layer, isLeft) -> bool:
	# BOTH SIDES MIRRORING EACH OTHER WOULD RECURSE FOR EVER AND MEANS NOTHING;
	# TREAT THAT AS NEITHER.
	if layer.userData[LEFT.key('Mirror')] and layer.userData[RIGHT.key('Mirror')]:
		return False
	return bool(layer.userData[of(isLeft).key('Mirror')])

# SPLIT A PATH INTO ITS SUBPATHS AND MERGE THEM INTO ONE WALL.
# THE MERGE ITSELF IS IN BKAutoBubble.union_walls, WHICH IS PURE AND TESTED;
# THIS IS THE NSBezierPath WRAPPER AROUND IT.
def unionSubpaths(bubblePath, isLeft) -> NSBezierPath:
	try:
		if bubblePath is None:
			return None
		subpaths, current = [], []
		for i in range(bubblePath.elementCount()):
			kind, points = bubblePath.elementAtIndex_associatedPoints_(i)
			if kind == 0:  # moveTo: a new piece starts here
				if len(current) > 1:
					subpaths.append(current)
				current = [(points[0].x, points[0].y)]
			else:
				current.append((points[0].x, points[0].y))
		if len(current) > 1:
			subpaths.append(current)
		if len(subpaths) < 2:
			return bubblePath  # the common case: nothing to merge

		import BKAutoBubble
		merged = BKAutoBubble.union_walls(subpaths, keep_min=isLeft)
		merged = BKAutoBubble.taut_join(merged, subpaths, keep_min=isLeft)
		if not merged:
			return bubblePath
		united = NSBezierPath.alloc().init()
		for i, (x, y) in enumerate(merged):
			if i == 0:
				united.moveToPoint_(NSPoint(x, y))
			else:
				united.lineToPoint_(NSPoint(x, y))
		return united
	except Exception:
		log(f'unionSubpaths error: {traceback.format_exc()}', error=True)
		return bubblePath

def getFinalBubble(layer, isLeft=True) -> NSBezierPath:
	# look for the bubble information for all components
	bubbleAttributes = gatherBubbleInfo(layer, isLeft=isLeft)

	if bubbleAttributes:
		bp = buildBubble(theAttributes=bubbleAttributes, isLeft=isLeft, bubblePath=None, inheritedTransforms=[])
		# buildBubble returns one polyline PER COMPONENT for a composite, and
		# getKernValue walks a wall as a single bottom-to-top line. Merge them
		# into one before anybody reads it.
		bp = unionSubpaths(bp, isLeft)
		# NO WIDTH SHIFT HERE ANY MORE: buildBubble places each wall against the
		# advance of the layer that DREW it, which is the same thing for a glyph
		# with its own wall and the only correct thing for a component.
		return bp
	return None

	# emergency pass through


def x_at_y(p0, p1, y):
	if p1.y == p0.y:
		t = y - p0.y
	else:
		t = (y - p0.y) / (p1.y - p0.y)
	return p0.x + t * (p1.x - p0.x)

def getKernValue(bubblePathL: NSBezierPath, bubblePathR: NSBezierPath, widthL: int, debug=False, withRow=False, space=0.0):
	# withRow ALSO RETURNS THE HEIGHT AT WHICH THE TWO WALLS COME CLOSEST,
	# WHICH IS THE HALF A DESIGNER NEEDS: IT NAMES THE NODE DECIDING THE PAIR.
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
		
		if debug:
			log(f'lineA: {lineA}')
			log(f'lineB: {lineB}')

		i = j = 0
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
					distances.append((xb - xa, y))

			# advance the segment that ends first
			if a1.y < b1.y:
				i += 1
			else:
				j += 1

		if debug:
			log(distances)

		if not distances:
			# THE TWO BUBBLES NEVER MEET VERTICALLY - `hyphen` AGAINST
			# `quoteright`, `period` AGAINST `quoteleft`. NOTHING BRINGS THEM
			# TOGETHER, SO THE KERN IS ZERO. NOT INFINITY, WHICH IS THE
			# FAIL-SAFE FOR A BROKEN BUBBLE. See CLAUDE.md.
			return (0.0, None) if withRow else 0.0

		closest = min(distances)
		if space:
			# AIR BETWEEN THE TWO BUBBLES, one rule for the kerner and the fit
			# alike: it moves only pairs that already kern, and never past 0.
			import BKAutoBubble
			closest = (-BKAutoBubble.with_fit(-closest[0], space), closest[1])
		return closest if withRow else closest[0]
	except ValueError:
		# log(f'getKernValue error: {traceback.format_exc()}', error=True)
		# if error occurs, return infinite kern value to trigger fail-safe
		return (float("inf"), None) if withRow else float("inf")


# KERN GENERATION LOGIC

def resolveReference(layer, side, limit=16):
	# THE GLYPH AT THE END OF A REFERENCE CHAIN, OR None IF THIS SIDE IS ITS OWN.
	try:
		name = layer.userData[side.key('Refer')]
		if not name:
			return None
		f = layer.font()
		masterId = layer.associatedMasterId
		seen = {layer.parent.name}
		while name and limit > 0:
			if name in seen:
				return None  # circular; no group can be made of it
			seen.add(name)
			g = f.glyphs[name]
			if g is None:
				return None
			nextLayer = g.layers[masterId]
			nextName = nextLayer.userData[side.key('Refer')] if nextLayer else None
			if not nextName:
				return name
			name, limit = nextName, limit - 1
		return None
	except Exception:
		log(f'resolveReference error: {traceback.format_exc()}', error=True)
		return None

def bubbleGroups(font, masterId):
	# -> ({glyph: rightGroup}, {glyph: leftGroup}), INCLUDING EACH GROUP'S OWN
	# REPRESENTATIVE, WHICH IS A MEMBER OF ITS OWN GROUP.
	#
	# A BUBBLE REFERENCE IS ALREADY A KERNING GROUP, AND AN EXACT ONE: EVERY
	# MEMBER'S WALL IS LITERALLY THE REPRESENTATIVE'S, RESOLVED THROUGH
	# getFinalBubble, SO ONE KERN VALUE FOR THE GROUP IS NOT AN APPROXIMATION OF
	# THE MEMBERS' VALUES - IT IS THEIR VALUE. THE ADVANCE DOES NOT ENTER INTO
	# IT EITHER: A WALL IS STORED AGAINST THE ORIGIN AND THE ADVANCE, AND
	# getKernValue TAKES THE WIDTH BACK OUT AGAIN.
	right, left = {}, {}
	for glyph in font.glyphs:
		layer = glyph.layers[masterId]
		if layer is None:
			continue
		for side, table in ((RIGHT, right), (LEFT, left)):
			target = resolveReference(layer, side)
			if target:
				table[glyph.name] = target
				table[target] = target
	return right, left


# 　function that rounds up the given number to nearest 10, used for applying minimal kernValue
# I use this because kern value may be negative.
def roundup(givenNumber):
	return int(math.ceil(givenNumber / 10.0)) * 10


def namesByCharacter(font):
	"""Which glyph draws each character in this font. -> {str: str}

	The relevant-pair list is written in characters and the kerner deals in
	glyph names, so something has to hold the two together, and only the font
	knows. A character the font cannot draw simply does not appear.
	"""
	table = {}
	try:
		for glyph in font.glyphs:
			values = list(glyph.unicodes or [])
			if glyph.unicode and glyph.unicode not in values:
				values.append(glyph.unicode)
			for value in values:
				try:
					character = chr(int(value, 16))
				except Exception:
					continue
				# FIRST GLYPH WINS. Two glyphs claiming one character is a broken
				# font, and picking the later one would only make it arbitrary.
				table.setdefault(character, glyph.name)
	except Exception:
		log(f'namesByCharacter error: {traceback.format_exc()}', error=True)
	return table


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

		# GROUP MODE: A PAIR IS DECIDED BY THE TWO WALLS, AND MEMBERS OF A BUBBLE
		# GROUP SHARE ONE WALL, SO EVERY PAIR IN A GROUP HAS ONE ANSWER. WRITING
		# IT ONCE COLLAPSES THE PAIR COUNT BY ROUGHLY THE SQUARE OF THE AVERAGE
		# GROUP SIZE AND LEAVES A KERNING TABLE A PERSON CAN OPEN AND READ.
		import BKAutoBubble
		# ONLY THE PAIRS THAT TURN UP IN REAL TEXT, if asked. A preset is a
		# cartesian product - uppercase against uppercase is 676 pairs - and
		# most of those two letters never stand together in any language. This
		# keeps the preset deciding WHICH GLYPHS are in scope and lets the list
		# throw out the combinations nobody will ever set.
		#
		# BEFORE THE GROUPS COLLAPSE, because after it pairsList is keyed by
		# group name and the list is written in glyphs.
		if bool(BKAutoBubble._pref(BKAutoBubble.PREF_RELEVANT_ONLY, False)):
			relevant = BKAutoBubble.relevant_pair_names(namesByCharacter(f))
			if relevant:
				pairsList = {pair for pair in pairsList if pair in relevant}
		useGroups = bool(BKAutoBubble._pref(BKAutoBubble.PREF_KERN_GROUPS, False))
		# Read ONCE: the loop below runs over every pair in the preset, and
		# both of these come from the font's upm and a preference.
		space = BKAutoBubble.fit_space(f, m)
		threshold = BKAutoBubble.min_kern(f)
		rightGroups, leftGroups = bubbleGroups(f, m.id) if useGroups else ({}, {})
		if useGroups:
			for name, group in rightGroups.items():
				if f.glyphs[name]:
					f.glyphs[name].rightKerningGroup = group
			for name, group in leftGroups.items():
				if f.glyphs[name]:
					f.glyphs[name].leftKerningGroup = group
			# ONE ENTRY PER GROUP PAIR, KEYED BY WHAT TO WRITE AND WHAT TO MEASURE
			grouped = {}
			for left, right in pairsList:
				keyL = '@MMK_L_' + rightGroups[left] if left in rightGroups else left
				keyR = '@MMK_R_' + leftGroups[right] if right in leftGroups else right
				grouped[(keyL, keyR)] = (rightGroups.get(left, left), leftGroups.get(right, right))
			pairsList = grouped

		charsToUse = {glyph for pair in (pairsList.values() if useGroups else pairsList) for glyph in pair}
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
		previousProgress = 0
		for i, pair in enumerate(pairsList):
			# for progress bar update
			currentProgress = round(100*i/pairsCount)
			if currentProgress > previousProgress:
				previousProgress = currentProgress
				yield currentProgress

			if useGroups:
				keyL, keyR = pair
				left, right = pairsList[pair]  # the representatives to measure
			else:
				keyL, keyR = pair
				left, right = pair
			# I think bubblesDic is already cleared?

			widthL = f.glyphs[left].layers[m.id].width
			# no more than half of the narrower glyph
			maxKern = ( min(widthL, f.glyphs[right].layers[m.id].width,) / 2 )

			# figure out the kern value here
			# log(f'{type(bubblesDic[left]["RB"])} {type(bubblesDic[right]["LB"])} {type(widthL)}')

			debug = False
			rawKern = getKernValue(bubblesDic[left]['RB'], bubblesDic[right]['LB'], int(widthL), debug=debug, space=space)
			kernValue = round(rawKern) if not math.isinf(rawKern) else rawKern
		
			if debug:
				log(f'Left =  {left}:', type(bubblesDic[left]['RB']))
				log(f'Right = {right}:', type(bubblesDic[right]['LB']))
				log(f'kernValue: {kernValue}')

			if kernValue < maxKern:
				if abs(kernValue) >= threshold:
					f.setKerningForPair(m.id, keyL, keyR, -kernValue)
				elif abs(kernValue) >= threshold * 0.8:
					# NEARLY BIG ENOUGH. Toschi rounded 8-10 up to 10 rather than
					# dropping it, and the nicety generalises to any threshold.
					f.setKerningForPair(m.id, keyL, keyR,
						-int(math.copysign(round(threshold), kernValue)))
			else:  # activates fail-safe by using maxKern if kernValue is too large or infinite
				f.setKerningForPair(m.id, keyL, keyR, -int(maxKern))

			# THE END
			f.enableUpdateInterface()
	except Exception:
		log(f'kernOpenType error: {traceback.format_exc()}', error=True)


# to be run from BK Tool. The measurement lives in BKAutoBubble; this is the
# name the rest of the plugin already knew it by.
def autoBuildBubble(layer, isLeft=True):
	try:
		# imported here, not at the top: BKAutoBubble takes log() from this
		# module, and importing it up there would close the circle.
		import BKAutoBubble
		side = BKAutoBubble.LEFT if isLeft else BKAutoBubble.RIGHT
		return BKAutoBubble.auto_bubble_nodes(
			layer, side,
			grid=BKAutoBubble.resolve_grid(layer.font(), layer.associatedFontMaster()))
	except Exception:
		log(f'autoBuildBubble error: {traceback.format_exc()}', error=True)
		return None
