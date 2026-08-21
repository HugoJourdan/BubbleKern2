# encoding: utf-8
"""Automatic bubble generation and grouping for BubbleKern.

A bubble side is a polyline in the whitespace beside a glyph, and what it is
FOR is to meet the neighbour's bubble at the distance the designer wants. So
the shape to generate is the frontier of the glyph's own ink, pushed outward
by one gap: `T` opens up under its arm because its ink recedes there, `o` hugs
its curve, and a neighbour meets both at the same distance.

The measurement half is PORTED from AZ-Fingerprints (that plugin's
`azfingerprints.py`, taken 2026-08-18) rather than imported, because it is a
separate bundle BubbleKern cannot assume is installed. The ported functions
keep their original docstrings: those record what was measured against three
families' hand-drawn kerning groups, and rewriting them here would invent a
second, unmeasured story. Diff the two files to see drift.

Indentation is 4 spaces, not the tabs of the rest of this plugin, because most
of the file is that verbatim copy.

Everything except the layer scan is pure, so the suite in
`tests/test_bkautobubble.py` runs without Glyphs.
"""

import json
import math
import os
import re

from BKSide import LEFT, RIGHT  # noqa: F401  (re-exported; see below)

try:
    from BKCommonLogic import log
except ImportError:  # tests import this module without GlyphsApp
    def log(message='', error=None):
        pass


# --- Ported constants -----------------------------------------------------

# THE TWO SIDES COME FROM `BKSide`. They are still exactly "L" and "R" - `Side`
# is a str subclass whose string is the letter - so the ported code below, which
# uses them as dict keys, cannot tell the difference.

# A side needs this many scanlines before it is worth measuring at all.
MIN_ROWS_TO_MEASURE = 6

# How close to a scanline a node has to be to count as sitting on it, in font
# units. Far below anything a designer can draw, far above the float noise
# that decides whether an extremum is "exactly" on a row.
ROW_EPS = 0.01

MIN_OVERLAP_ROWS = 3

# A neighbour cannot reach into a concavity at an arbitrary angle, so a
# profile is clamped to recede no faster than this per row. The clamp is what
# makes `h` cluster with `n` while `H` stays apart.
S1_SLOPE = 1.76

# 1% of the em to group two sides. 0.012 and 0.014 both scored lower AND lost
# `h` out of `@n` on ABC Social.
GROUP_TOL_EM = 0.01

MEDOID_ROUNDS = 2

# Last-resort tie-break between equally central candidates: convention says a
# cap stem keys to H and a lowercase stem to n.
PREFERRED_ANCHORS = (
    "o", "n", "H", "O", "h", "l", "I", "d", "b", "p", "q",
    "A", "V", "E", "T", "m", "u", "c",
)

# `uniE018`, `u1F600`, `uniE012.ss01` - a codepoint is not a name.
CODEPOINT_NAME = re.compile(r"^u(ni)?[0-9A-Fa-f]{4,6}(\.|$)")


# --- BubbleKern's own constants -------------------------------------------

# Nodes a generated bubble may have, and how coarsely it is thinned - the
# tolerance in raster steps, so it scales with the em like everything else.
# Measured on BK Test Serif, against a wall with a node on every scanline:
#
#     tolerance/cap    nodes avg    worst kern drift
#     5 / 12                 7.6            4 units
#     10 / 8                 6.4            9
#     20 / 8                 5.9           11
#     30 / 6                 4.7           27
#     60 / 4                 2.9           98
#
# 10/8 is where a third of the nodes go for a drift a designer would not
# notice on a starting shape. Past 20 the wall stops describing the glyph:
# at 60 an `o` is three nodes and kerns 98 units off.
DEFAULT_MAX_NODES = 8
TOLERANCE_STEPS = 2

# Runs of nodes whose x values sit within this fraction of the em of each other
# are put on ONE x. A wall measuring -33, -32, -31 down a flat side is
# describing a straight edge with a unit of noise on it, and every node spent
# on that noise is a node not spent on the shape. Half a per cent of the em is
# 5 units at 1000 upm: below what anyone draws to, and below what the kerning
# can see.
ALIGN_EM = 0.005

# No two nodes of a generated wall end up closer together than this fraction of
# the em. One per cent is 10 units at 1000 upm. Two nodes four units apart are
# not describing a feature - nothing in the kerning can see four units, and
# nobody editing the wall by hand can grab one without grabbing the other -
# so they are a node's worth of cost for none of a node's worth of shape.
# The simplifier works on DEVIATION and will happily keep a close pair that
# sits on a real corner, which is where these come from; this is the floor
# that says a corner is not worth two nodes if they are on top of each other.
MIN_GAP_EM = 0.01

# The deepest a generated wall may sit inside the advance, as a fraction of the
# em. This is the knob that bounds a DIAGONAL. The turn angle limits how fast a
# wall may cut inward and says nothing about how far, so against a long
# diagonal - the right side of an `A`, the left of a `V` - the wall follows the
# ink all the way in and the pair kerns -261. What a designer draws there is a
# near-vertical line a fixed distance in, and capping the inset produces
# exactly that. Measured on BK Test Serif at a cap of 85 units: A|V -85, T|o
# -85, L|y -80, while n|n and H|H stay at 0. upm/12 is that cap at 1000 upm,
# and it reads as what it is - the deepest single kern the font will propose.
MAX_INSET_PERCENT = 10.0  # of the LAYER'S ADVANCE, and the floor of INSET_RANGE

# How much of a wall's horizontal excursion to keep, 0 to 1. Flattening is
# measured from the OUTERMOST point and never from the mean: pulling a wall
# toward its mean would push its widest place INWARD, behind the ink, and a
# bubble that no longer contains its own glyph lets a pair collide. Toward the
# outermost, every value can only get smaller, so the wall stays outside the
# ink and the kerning only ever loosens. 1 is the measured profile; 0 is a
# straight vertical wall at the outermost point.
AMPLITUDE = 1.0

# How sharply a WALL may turn inward, in degrees off vertical. Not S1_SLOPE:
# that one is 60 degrees and was measured for GROUPING, where it decides
# whether `h` belongs with `n`. Drawing is a different question, and 60 degrees
# draws a deep step wherever a glyph's side falls away - under the bowl of a
# `P`, where the wall dives 300 units in 130 and then runs flat to the
# baseline. Measured on BK Test Serif, dropping the wall to 35 degrees costs
# nothing and improves several pairs: T|o goes -164 to -105 and F|a -125 to
# -73, while L|y (-92), r|n (-1), P|a, o|o and n|n all hold. Below 27 degrees
# it starts eating tucks a designer wants - L|y collapses to -57.
WALL_ANGLE = 35.0
WALL_SLOPE = math.tan(math.radians(WALL_ANGLE))

GRID_PARAMETER = "BubbleKernGrid"
# One parameter, on the font or on a master, holding the settings that decide
# what gets WRITTEN to the file. The preview switches are not in it: where a
# person points their eyes is not a property of the drawing.
SETTINGS_PARAMETER = "BubbleKern"
PREF_GRID_ON = "com.Tosche.BubbleKern.grid.on"
PREF_GRID_Y = "com.Tosche.BubbleKern.grid.y"
PREF_TOLERANCE = "com.Tosche.BubbleKern.auto.tolerance"
PREF_WALL_ANGLE = "com.Tosche.BubbleKern.auto.wallAngle"
PREF_MAX_INSET = "com.Tosche.BubbleKern.auto.maxInset"
PREF_AMPLITUDE = "com.Tosche.BubbleKern.auto.amplitude"
PREF_PREVIEW_KERN = "com.Tosche.BubbleKern.previewKern"
PREF_FOLLOW_SPACING = "com.Tosche.BubbleKern.followSpacing"
PREF_KERN_GROUPS = "com.Tosche.BubbleKern.kernGroups"
PREF_RELEVANT_ONLY = "com.Tosche.BubbleKern.relevantOnly"
PREF_PREVIEW_TEXT = "com.Tosche.BubbleKern.previewText"
PREF_PREVIEW_WALLS = "com.Tosche.BubbleKern.previewWalls"
PREF_PREVIEW_KERNED = "com.Tosche.BubbleKern.previewKerned"
PREF_FIT_TEXT = "com.Tosche.BubbleKern.fitText"
PREF_FIT = "com.Tosche.BubbleKern.fit"
PREF_MIN_KERN = "com.Tosche.BubbleKern.minKern"
# Per cent of the size that would fit the box: 100 is "as big as it goes".
PREF_PREVIEW_SIZE = "com.Tosche.BubbleKern.previewSize"


# --- Ported from AZ-Fingerprints ------------------------------------------


def bevel_profile(profile, step, slope=S1_SLOPE):
    """Clamp a recession profile so it cannot recede faster than `slope`.

    Both sides arrive as depth INWARD from the edge, so "more recessed" is
    always a larger number and one pass serves both. Two sweeps — down, then
    up — give the cone: each row is limited by its neighbours plus what the
    slope allows over that distance.
    """
    if not profile:
        return {}
    rows = sorted(profile)
    beveled = dict(profile)
    for previous, row in zip(rows, rows[1:]):
        limit = beveled[previous] + slope * step * (row - previous)
        if beveled[row] > limit:
            beveled[row] = limit
    for row, following in reversed(list(zip(rows, rows[1:]))):
        limit = beveled[following] + slope * step * (following - row)
        if beveled[row] > limit:
            beveled[row] = limit
    return beveled


def kern_profiles(rows, width, step):
    """The kern-relevant profile of each side. -> {LEFT: {...}, RIGHT: {...}}

    Measured from the ORIGIN and the ADVANCE, not from the ink's own extremes:
    that is the whitespace a neighbour actually sees.
    """
    left = {row: xs[0] for row, xs in rows.items()}
    right = {row: width - xs[1] for row, xs in rows.items()}
    return {
        LEFT: bevel_profile(left, step),
        RIGHT: bevel_profile(right, step),
    }


def cone_limits(profile, step, slope=S1_SLOPE):
    """Everything needed to ask a profile "how far do you reach at row R?".

    -> (low_row, high_row, from_below, from_above)

    The frontier past a glyph's own band is the lower envelope of a cone from
    EVERY inked row, not just from the nearest one: a row further away but far
    less recessed can still be what a neighbour meets first. Written out, the
    envelope below the band is

        min over q of (depth[q] + rise * (q - row))
            = (min over q of (depth[q] + rise * q)) - rise * row

    — a straight line whose intercept does not depend on the row. So two
    numbers per profile answer every query in constant time, which matters
    because clustering asks n squared times.
    """
    rise = slope * step
    return (
        min(profile),
        max(profile),
        min(depth + rise * row for row, depth in profile.items()),
        min(depth - rise * row for row, depth in profile.items()),
    )


def cone_depth(limits, row, step, slope=S1_SLOPE):
    """The frontier `limits` describes, at one row. -> depth inward."""
    low, high, from_below, from_above = limits
    rise = slope * step
    if row < low:
        return from_below - rise * row
    if row > high:
        return from_above + rise * row
    # A hole INSIDE the band — `equal`, `divide`. Rows sit on both sides of it,
    # so both lines are candidates and neither over-reaches by much.
    return min(from_below - rise * row, from_above + rise * row)


def kern_fit(a, b, step, limits_a=None, limits_b=None):
    """How far two sides are from kerning alike. -> float, or inf.

    The same shared-band term as `kern_distance`, but a row only one of them
    occupies costs what its ink puts in the neighbour's way rather than a flat
    rate: past its own band the other glyph's frontier recedes along the cone,
    and this charges only where the first protrudes INTO it. `eng`'s descender
    sits far behind `n`'s cone and costs nothing; `p`'s stem runs straight down
    through it and costs plenty. Empty space is not a difference.

    Hugo, twice, from the drawing rather than from the numbers: `eng` should
    not be flagged against `n`, and `h` SHOULD group with `n` and `m` on the
    right. Both are the same blind spot — the flat rate charged `h` 90 to 105
    units for the ascender rows `n` does not have, when the right side of an
    `h` is a shoulder like any other. Under the cone they are 3 to 11 apart,
    and the designers of ABC Diatype and ABC Walter Neue both put `h` in `@n`.
    Where `l` and `r` genuinely differ they stay 110 to 130 away.

    Measured against the hand-drawn groups of three families, both sides, this
    is a wash on aggregate — mean F1 78.9 against 79.5 for the flat rate — and
    it is right about the cases a designer can name, which the aggregate is
    too coarse to see. It also leaves ONE measurement where there were two.

    `limits_a`/`limits_b` are `cone_limits` results, hoisted out by callers
    that ask about the same profile many times.
    """
    shared = a.keys() & b.keys()
    if len(shared) < MIN_OVERLAP_ROWS:
        return float("inf")
    if limits_a is None:
        limits_a = cone_limits(a, step)
    if limits_b is None:
        limits_b = cone_limits(b, step)
    total = 0.0
    for row in a.keys() | b.keys():
        if row in a and row in b:
            total += abs(a[row] - b[row])
        elif row in a:
            total += max(0.0, cone_depth(limits_b, row, step) - a[row])
        else:
            total += max(0.0, cone_depth(limits_a, row, step) - b[row])
    return total / len(shared)


def kern_medoid(members, profiles, step, limits=None):
    """The member closest to all the others — the CENTRE of the group.

    A leader is whichever glyph happened to come first alphabetically; the
    medoid is the one the group actually looks like. It is not what the group
    is called (`kern_group_name`), it is what the settling pass measures
    against.
    """
    if len(members) == 1:
        return members[0]
    if limits is None:
        limits = {name: cone_limits(profiles[name], step) for name in members}
    best = members[0]
    best_cost = float("inf")
    for name in members:
        cost = 0.0
        for other in members:
            if other == name:
                continue
            distance = kern_fit(
                profiles[name], profiles[other], step,
                limits[name], limits[other],
            )
            cost += 1e12 if distance == float("inf") else distance
        if cost < best_cost:
            best_cost = cost
            best = name
    return best


def name_rank(name):
    """Position in PREFERRED_ANCHORS; unlisted glyphs all tie at the end."""
    try:
        return PREFERRED_ANCHORS.index(name)
    except ValueError:
        return len(PREFERRED_ANCHORS)


def name_simplicity(name):
    """Sort key: the plainest way to name a group comes first.

    Convention list, then a real name over a codepoint, then no suffix, then
    the shorter name. `o` before `e` before `eacute` before `e.ss01`, because
    a group called `@eacute` reads as a group OF accented glyphs when it is
    really the round right side, and the accent is the part a neighbour never
    sees. Codepoints rank before the suffix test rather than after it: on
    measured groups `copyright` lost to `uniE018` on length alone, and
    `five.blackCircled` says more than `uniE012` however many dots it has.
    """
    return (
        name_rank(name),
        bool(CODEPOINT_NAME.match(name)),
        name.count("."),
        len(name),
        name,
    )


def kern_group_name(members, profiles, step, limits=None):
    """What to CALL a cluster. -> one of its members.

    Not the medoid. Every member is within tolerance of every other — that is
    what `cluster_kern_side` enforces — so any of them names the group equally
    correctly, and the choice is only about which name a designer can read.
    Centrality survives as the tie-break between equally plain names, which is
    the same order the metric-key side has used all along.
    """
    if len(members) == 1:
        return members[0]
    centre = kern_medoid(members, profiles, step, limits)
    return min(members, key=lambda name: (name_simplicity(name), name != centre))


def cluster_kern_side(profiles, tolerance, step, rounds=MEDOID_ROUNDS):
    """Cluster one side's profiles. -> {group_name: [members]}

    A glyph joins the group it fits BEST, and fitting means being within
    tolerance of every member — not just of whichever glyph happened to start
    the group, which is how OpticalKern (and this, until it was measured) does
    it. Then a few rounds of moving every glyph to the nearest group MEDOID,
    because the greedy pass sees each glyph once, in alphabetical order, and a
    group that has drifted since cannot take back what it lost.

    Scored by pairs against the hand-drawn groups in ABC Social, ABC Diatype
    and ABC Walter Neue, both sides — six sets in all — mean F1 went 75.7 ->
    78.9 against the greedy leader cover this replaces, and precision rose on
    every one of the six. That trade is the one a proposal list wants: a wrong
    proposal is on screen with a green mark next to it, a missing one costs
    nothing. Rejected on the same measurements: full agglomerative complete
    linkage (identical to within a point, needs the whole distance matrix),
    single linkage (69.9), seeding by centrality rather than alphabetically,
    and MISMATCH_WEIGHT at 0.25 and 1.0.
    """
    # Hoisted: `kern_fit` would otherwise re-scan both profiles for their band
    # and their cone on every one of n-squared comparisons.
    limits = {name: cone_limits(profile, step) for name, profile in profiles.items()}
    groups = []
    for name in sorted(profiles):
        profile = profiles[name]
        best = None
        best_distance = tolerance
        for group in groups:
            worst = 0.0
            for member in group:
                distance = kern_fit(
                    profile, profiles[member], step, limits[name], limits[member]
                )
                if distance > tolerance:
                    worst = float("inf")
                    break  # ponytail: most groups fail on their first member
                if distance > worst:
                    worst = distance
            if worst <= best_distance:
                best = group
                best_distance = worst
        if best is None:
            groups.append([name])
        else:
            best.append(name)
    for _ in range(rounds):
        medoids = [kern_medoid(group, profiles, step, limits) for group in groups]
        landing = [[] for _ in medoids]
        for name in sorted(profiles):
            profile = profiles[name]
            best = None
            best_distance = tolerance
            for slot, medoid in enumerate(medoids):
                if medoid == name:
                    best = slot
                    break  # a group's own medoid never leaves it
                distance = kern_fit(
                    profile, profiles[medoid], step, limits[name], limits[medoid]
                )
                if distance <= best_distance:
                    best = slot
                    best_distance = distance
            if best is None:
                landing.append([name])
            else:
                landing[best].append(name)
        groups = [group for group in landing if group]
    return {
        kern_group_name(members, profiles, step, limits): members
        for members in groups
        if len(members) > 1
    }


def rows_from_segments(segments, step):
    """Scanline crossings of flattened line segments. -> {row: (min_x, max_x)}

    Walks the SEGMENTS and visits only the rows each one spans, rather than
    walking the rows and testing every segment against each: a glyph has a few
    hundred segments and a hundred rows, and the second shape is the product
    of the two while this one is just the crossings.

    INCLUSIVE on both ends (`lo <= y <= hi`), which is not the usual scanline
    rule — and deliberately so. A crossing-parity rule exists to decide what
    is inside a shape, and this is not asking that: it wants the outermost INK
    on the row, so every point of the outline at that y counts, and a vertex
    counted twice does no harm to a min and a max.

    Parity gets it wrong where it matters most. `G`'s rightmost point sat
    exactly on a scanline, where the outline TOUCHES without crossing: parity
    dropped it and reported that side 553 units further in than it is. The
    extremes of a glyph are precisely the places outlines go tangent.
    """
    rows = {}
    for x1, y1, x2, y2 in segments:
        if y1 == y2:
            # Horizontal: no interpolation possible, but a flat edge sitting
            # on a scanline is still ink on that row.
            if abs(y1 / step - 0.5 - round(y1 / step - 0.5)) * step <= ROW_EPS:
                index = round(y1 / step - 0.5)
                low_x, high_x = (x1, x2) if x1 < x2 else (x2, x1)
                span = rows.get(index)
                rows[index] = (
                    low_x if span is None else min(span[0], low_x),
                    high_x if span is None else max(span[1], high_x),
                )
            continue
        low, high = (y1, y2) if y1 < y2 else (y2, y1)
        # Rows sit at (index + 0.5) * step, so the ones inside [low, high] are
        # ceil(low/step - 0.5) up to floor(high/step - 0.5) — widened by EPS,
        # because an extremum node landing on a scanline lands there to within
        # float noise, not exactly. Glyphs' own routine has the same allowance;
        # without it a vertex at y=345.0000001 misses the row at y=345.
        first = math.ceil((low - ROW_EPS) / step - 0.5)
        last = math.floor((high + ROW_EPS) / step - 0.5)
        low_x, high_x = (x1, x2) if x1 < x2 else (x2, x1)
        for index in range(first, last + 1):
            y = (index + 0.5) * step
            x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            # The widening can extrapolate a hair past the segment's own end.
            x = low_x if x < low_x else (high_x if x > high_x else x)
            span = rows.get(index)
            if span is None:
                rows[index] = (x, x)
            elif x < span[0]:
                rows[index] = (x, span[1])
            elif x > span[1]:
                rows[index] = (span[0], x)
    return rows


def is_mark(glyph):
    """A nonspacing mark — an accent, not part of what a neighbour sees."""
    if glyph is None:
        return False
    return glyph.category == "Mark" or glyph.subCategory == "Nonspacing"


def outline_paths(layer, skip_marks=False):
    """The NSBezierPaths to measure. -> [path]

    Normally one: `completeBezierPath`, because it includes COMPONENTS — a
    composite has no paths of its own and measuring it without them would
    report no ink at all. Its overlap removal costs nothing here, since the
    profile only ever reads the outermost crossing on each side.

    `skip_marks` takes the layer apart instead and leaves the accents out.
    That is for KERNING only: `aacute` sat 85 units from `a` and every
    accented glyph in the file was flagged as no longer fitting its group —
    all of it the row-mismatch penalty, charged for the 17 rows of an acute
    that no neighbour is ever spaced against. The shared rows agreed exactly.
    """
    if skip_marks:
        paths = []
        try:
            own = layer.bezierPath
            if own is not None and not own.isEmpty():
                paths.append(own)
            for component in layer.components:
                if is_mark(component.component):
                    continue
                # Already transformed into the layer's coordinates, unlike
                # `componentLayer.bezierPath`, which is the glyph as drawn.
                path = component.bezierPath
                if path is not None and not path.isEmpty():
                    paths.append(path)
        except Exception:  # noqa: BLE001 - fall through to the whole layer
            paths = []
        if paths:
            return paths
        # Nothing left once the marks are gone: this IS a mark, so measure it.
    for name in ("completeBezierPath", "bezierPath"):
        try:
            path = getattr(layer, name)
        except Exception:  # noqa: BLE001 - try the other one
            path = None
        if path is not None and not path.isEmpty():
            return [path]
    return []


def layer_segments(layer, skip_marks=False):
    """The layer's outline flattened to line segments. -> [(x1, y1, x2, y2)]"""
    segments = []
    for path in outline_paths(layer, skip_marks):
        # No setFlatness_: measured on this build, it changes neither the
        # segment count nor the bounds — the flattened path reproduces the raw
        # path's extremes exactly — so the copy it would need is not worth it.
        flat = path.bezierPathByFlatteningPath()
        start = current = None
        for index in range(flat.elementCount()):
            kind, points = flat.elementAtIndex_associatedPoints_(index)
            if kind == 0:  # moveTo
                start = current = (points[0].x, points[0].y)
            elif kind == 1:  # lineTo
                following = (points[0].x, points[0].y)
                if current is not None:
                    segments.append(
                        (current[0], current[1], following[0], following[1])
                    )
                current = following
            elif kind == 3:  # closePath
                if current is not None and start is not None:
                    segments.append((current[0], current[1], start[0], start[1]))
                current = start
    return segments


def scan_layer(layer, step, skip_marks=False):
    """Horizontal scanlines across one layer.

    -> ({row_index: (leftmost_x, rightmost_x)}, min_x, max_x) or None.

    Rows sit on a grid shared by every glyph, offset by half a step so a flat
    baseline or a flat x-height is never grazed exactly.
    """
    bounds = layer.bounds
    width = bounds.size.width
    height = bounds.size.height
    if width <= 0 or height <= 0:
        return None
    min_x = bounds.origin.x
    max_x = min_x + width
    bottom = bounds.origin.y
    top = bottom + height
    # One flattened path beats ~90 crossings into ObjC per layer: measuring a
    # 780-glyph file went from 22s to a fraction of it, and measuring was 96%
    # of the scan. The old path stays as a fallback — it is the reference
    # implementation, and a layer this cannot flatten still has to be read.
    segments = layer_segments(layer, skip_marks)
    if segments:
        rows = rows_from_segments(segments, step)
        if rows:
            return rows, min_x, max_x
    probe_left = min_x - 10
    probe_right = max_x + 10
    rows = {}
    for index in range(math.floor(bottom / step), math.ceil(top / step) + 1):
        y = (index + 0.5) * step
        if y <= bottom or y >= top:
            continue
        points = layer.intersectionsBetweenPoints(
            (probe_left, y), (probe_right, y), components=True
        )
        if len(points) <= 2:
            continue  # first and last are the probe ends, not ink
        xs = [point.x for point in points[1:-1]]
        rows[index] = (min(xs), max(xs))
    return rows, min_x, max_x


def raster_step(font):
    """upm/200 -> 5u rows at 1000 upm.

    Twice the rows it used to read (Hugo, 2026-08-16): a cap is ~154 samples
    a side rather than ~77, so a feature between 5 and 10 units deep now
    counts towards a match instead of falling between two rows.

    Measuring is most of what a scan costs, so this is also what a scan costs
    twice as much of.
    ponytail: this is the knob to turn if a big file scans slowly.
    """
    return max(2, round(font.upm / 200.0))


# --- The wall -------------------------------------------------------------

# Both sides arrive from `kern_profiles` as a depth measured INWARD from the
# origin and from the advance, which is the whitespace a neighbour sees,
# current spacing included. BubbleKern stores left x absolute from the origin
# and right x relative to the advance, so with one gap subtracted:
#
#     x_left(row)  =  depth(row) - gap
#     x_right(row) =  gap - depth(row)
#
# One wall serves both, negated for the right. Feeding those two walls back
# through `getKernValue` gives `2 * gap - min(depth_right_A + depth_left_B)`,
# so the gap is what decides where a generated pair lands. Left alone it is
# each side's OWN sidebearing, which puts every flat pair at exactly zero and
# leaves the spacing already in the file alone.


def layer_span(layer, master):
    """Vertical range a generated bubble covers. -> (low_y, high_y)

    The layer's own bounding box, which is what `resetBubble` and the tool's
    default bubble already use - a generated bubble that ran from the
    descender to the ascender on every glyph would disagree with every bubble
    the plugin draws by hand, and would claim height the glyph does not have.

    A layer with no ink at all (`space`) has no box to use, so it falls back
    to the master's own range.
    """
    bounds = layer.bounds
    if bounds.size.height > 0:
        return bounds.origin.y, bounds.origin.y + bounds.size.height
    return master.descender, master.ascender


def bubble_wall(profile, step, gap, low_y, high_y, max_depth, slope=WALL_SLOPE,
                max_inset=None):
    """The frontier of one side as a polyline. -> [(x, y)] bottom to top.

    x is depth-minus-gap, so a SMALLER x is further out into the whitespace on
    either side; `snap_points` and the simplifier both rely on that.

    Rows sit on the same half-offset grid every glyph is scanned on, so two
    generated bubbles have identical y ladders. `cone_depth` covers rows the
    glyph has no ink on: the frontier there recedes along the cone instead of
    stopping dead, which is what opens `T` up below its arm.
    """
    if not profile:
        return []
    # Rows strictly INSIDE the range, then both ends pinned to it exactly: a
    # scanline sits at (row + 0.5) * step and lands where it lands, and a
    # bubble that overhung its own bounding box by half a step would be
    # claiming height the glyph has not got.
    first = math.ceil(low_y / step - 0.5)
    last = math.floor(high_y / step - 0.5)
    if last < first:  # a glyph shorter than one scanline
        first = last = round((low_y + high_y) / 2.0 / step - 0.5)
    frontier = cone_frontier(profile, first, last, step, slope)
    # NOT OUTSIDE THE ADVANCE - UNLESS THE INK IS ALREADY OUT THERE.
    # `depth - gap` goes negative wherever a glyph is spaced tighter than the
    # gap, which is most rows of most glyphs, since the gap is the LARGER of
    # the two sidebearings; the floor is what pins those rows to the edge and
    # is how the tighter side gets calibrated at all.
    #
    # But a floor of zero also pins rows where the ink itself has left the
    # advance. `f` and `j` hang a hook or a tail over the edge and are given a
    # negative sidebearing for it - on BK Test Serif `f` is 396 wide with ink
    # to 474 - and the wall was being held at 396, seventy-eight units INSIDE
    # its own hook. The hook stuck out of its own bubble, and nothing kerning
    # against `f` could see the part of it that reaches furthest.
    #
    # So the floor is the edge, or the ink, whichever is further out. A wall
    # still never claims whitespace the glyph has not been given; ink over the
    # edge is whitespace the designer HAS given it, by spacing it that way.
    if max_inset is None:
        max_inset = float("inf")
    wall = [
        (min(max(min(0.0, frontier[row]), min(frontier[row], max_depth) - gap),
             max_inset), (row + 0.5) * step)
        for row in range(first, last + 1)
    ]
    if wall[0][1] > low_y:
        wall.insert(0, (wall[0][0], low_y))
    if wall[-1][1] < high_y:
        wall.append((wall[-1][0], high_y))
    return wall


def cone_frontier(profile, first_row, last_row, step, slope=S1_SLOPE):
    """Depth at EVERY row of a range, inked or not. -> {row: depth}

    `cone_depth` answers the same question in constant time and is what the
    clustering uses, but it is only exact OUTSIDE the profile's own band: in
    the gap between the bars of an `equal` it takes both cone lines from the
    band's far ends and lands far outside the glyph. That is harmless when
    charging one profile against another and wrong when the answer IS the
    drawing, so a wall sweeps instead - two passes over contiguous rows, each
    row limited by its neighbour plus what the slope allows. Rows of the
    profile outside the range still cast their cone into it.
    """
    rise = slope * step
    rows = list(range(first_row, last_row + 1))
    depth = {row: profile.get(row, math.inf) for row in rows}
    for row, value in profile.items():
        if row < first_row:
            depth[first_row] = min(depth[first_row], value + rise * (first_row - row))
        elif row > last_row:
            depth[last_row] = min(depth[last_row], value + rise * (row - last_row))
    for previous, row in zip(rows, rows[1:]):
        depth[row] = min(depth[row], depth[previous] + rise)
    for row, following in reversed(list(zip(rows, rows[1:]))):
        depth[row] = min(depth[row], depth[following] + rise)
    return depth


def flatten_wall(wall, amplitude=AMPLITUDE):
    """Keep only part of a wall's horizontal excursion. -> [(x, y)]

    Toward the outermost point, so a flattened wall is always a subset of the
    whitespace the unflattened one claimed - looser kerning, never tighter,
    and it can never end up behind the ink.
    """
    if not wall or amplitude >= 1.0:
        return wall
    amplitude = max(0.0, amplitude)
    outermost = min(x for x, _ in wall)
    return [(outermost + amplitude * (x - outermost), y) for x, y in wall]


def layer_gap(profiles):
    """The gap for one layer: the LARGER of its two sidebearings. -> float

    Each profile is depth measured inward from the origin or the advance, so
    its minimum IS that side's sidebearing. The larger of the two is the
    threshold at which BOTH walls land exactly on their edges: the wider side
    by arithmetic, the tighter one because the floor in `bubble_wall` takes
    over there - except on rows whose ink is outside the advance, where that
    floor gives way to the ink.

    Read off THIS layer rather than off `n`, which is what it used to be: one
    number for the whole font is only right for the glyphs spaced like the one
    it was read from. On BK Test Serif, `n`'s 47 was wider than most of the
    font and quietly loosened everything it did not fit.

    Each side's OWN sidebearing is the obvious alternative and is worse. It
    holds only while a glyph's two extremes sit at the same height: `l`, whose
    flag reaches 16 further left than its foot, kerned -16 against itself,
    where the larger sidebearing keeps it at 0 - the value its hand-drawn
    bubble gives.
    """
    depths = [min(profile.values()) for profile in profiles.values() if profile]
    return max(depths) if depths else 0.0


# --- Walls of more than one piece ------------------------------------------


def xs_at(wall, y):
    """Every x a bottom-to-top polyline has at one height. -> [x]

    Usually one. Two where a horizontal run sits exactly on the height asked
    for, and none at all above or below the polyline's own extent.
    """
    found = []
    for (x0, y0), (x1, y1) in zip(wall, wall[1:]):
        low, high = (y0, y1) if y0 <= y1 else (y1, y0)
        if low <= y <= high:
            if y1 == y0:
                found += [x0, x1]
            else:
                found.append(x0 + (y - y0) / float(y1 - y0) * (x1 - x0))
    return found


def union_walls(walls, keep_min=True):
    """Several polylines into one, row by row. -> [(x, y)]

    A composite's bubble arrives as one polyline per component - `Aacute` gives
    the `A` and the acute - and `getKernValue` walks a wall as a single
    bottom-to-top line, so it reads two of them as one that jumps from the top
    of the first to the bottom of the second. Every kern against a composite
    has been wrong for that reason.

    The union it needs is not a polygon union. The kerner only ever asks where
    a wall is at a given height, so taking the outermost x among the polylines
    that reach that height answers every question it can put - no intersection
    maths, no degenerate cases, no winding rules. `keep_min` is the left side,
    where a smaller x is further out; the right side keeps the maximum.

    Heights only one polyline reaches - the gap between an `A` and its accent -
    contribute their own node, so the result bridges the gap with one chord
    rather than pretending there is ink there.
    """
    walls = [wall for wall in walls if len(wall) >= 2]
    if len(walls) < 2:
        return list(walls[0]) if walls else []
    pick = min if keep_min else max
    merged = []
    for y in sorted({y for wall in walls for _, y in wall}):
        found = [x for wall in walls for x in xs_at(wall, y)]
        if found:
            merged.append((pick(found), y))
    return merged


def _cuts_in(first, middle, last, keep_min):
    """True if `middle` sits further IN than the chord from `first` to `last`.

    In, not out: a string pulled tight round the OUTSIDE of a wall rests on
    whatever reaches furthest into the whitespace and spans the dents between.
    Dropping what sticks out is the other operation entirely - it would trade a
    notch for a wall standing inside the ink it is supposed to keep clear.
    """
    cross = ((middle[1] - first[1]) * (last[0] - first[0])
            - (middle[0] - first[0]) * (last[1] - first[1]))
    return cross <= 0 if keep_min else cross >= 0


def _pull_taut(wall, low, high, keep_min):
    """One handover, from height `low` to `high`. -> [(x, y)]"""
    band = [node for node in wall if low <= node[1] <= high]
    if len(band) < 3:
        return wall
    taut = []
    for node in band:
        while len(taut) >= 2 and _cuts_in(taut[-2], taut[-1], node, keep_min):
            taut.pop()
        taut.append(node)
    if len(taut) == len(band):
        return wall
    return ([node for node in wall if node[1] < low] + taut
            + [node for node in wall if node[1] > high])


def taut_join(wall, walls, keep_min=True):
    """Pull a merged wall tight where one piece hands over to the next.

    Two pieces stacked one above the other - an O and the circumflex sitting
    over it - have nothing but air between them, and joining their walls end
    to end puts the whole difference between the two in a single step at the
    handover. It is honest to the ink, and it reads as a notch: the wall
    reverses direction and comes back, and a kern taken a few units higher
    lands somewhere else entirely.

    So the string is pulled tight across the handover, round the OUTSIDE.
    Anything lying further IN than the straight run between the pieces is what
    the notch is made of and goes; anything reaching further out is ink talking
    and the string rests on it. The wall can only ever move outward here, so a
    join can lose a bit of whitespace nobody was going to use but can never end
    up standing inside the ink.

    ponytail: the hull runs to the top of the upper piece, so a detailed accent
    keeps only its outward corners above the handover. Band it to the upper
    piece's first node or two if that ever loses something worth keeping.

    Pieces that overlap in height are two halves of one storey, not a
    handover, and are left to `union_walls` to settle row by row.
    """
    walls = [w for w in walls if len(w) >= 2]
    if len(walls) < 2 or len(wall) < 3:
        return wall
    spans = sorted((min(y for _, y in w), max(y for _, y in w)) for w in walls)
    for (_, lower_top), (upper_bottom, upper_top) in zip(spans, spans[1:]):
        if upper_bottom < lower_top:
            continue
        wall = _pull_taut(wall, lower_top, upper_top, keep_min)
    return wall


# --- Simplification and snapping ------------------------------------------


def _rdp(points, tolerance):
    """Ramer-Douglas-Peucker. -> [(x, y)] with the ends kept."""
    if len(points) < 3:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    scale = math.hypot(dx, dy)
    worst, index = 0.0, 0
    for position in range(1, len(points) - 1):
        x, y = points[position]
        if scale == 0:
            deviation = math.hypot(x - x0, y - y0)
        else:
            deviation = abs(dy * (x - x0) - dx * (y - y0)) / scale
        if deviation > worst:
            worst, index = deviation, position
    if worst <= tolerance:
        return [points[0], points[-1]]
    return _rdp(points[:index + 1], tolerance)[:-1] + _rdp(points[index:], tolerance)


def simplify(points, tolerance, max_nodes=DEFAULT_MAX_NODES):
    """Thin a wall down to something draggable. -> [(x, y)]

    The tolerance is raised until the result fits, rather than the worst nodes
    being dropped one by one: RDP keeps whichever points carry the shape, and
    asking it again with a coarser eye keeps that property. A wall of ~150
    rows comes out at a handful of nodes on a straight side.
    """
    max_nodes = max(2, max_nodes)
    if len(points) <= 2:
        return list(points)
    tolerance = tolerance if tolerance > 0 else 1.0
    thinned = _rdp(points, tolerance)
    while len(thinned) > max_nodes:
        tolerance *= 1.5
        thinned = _rdp(points, tolerance)
    return thinned


def align_columns(points, tolerance):
    """Put runs of nearly-equal x onto one line, and drop what that flattens.

    -> [(x, y)]

    Call it AFTER the simplifier, on the nodes that survived it, in WALL space.
    A wall that comes out -33, -32, -31 down a flat side is describing a
    straight edge with a unit of noise on it, and it is spending three nodes
    and two kinks on that unit. Runs whose x values all sit within `tolerance`
    of each other become one straight segment: the run's ends, at one x, with
    everything between them dropped.

    Not before the simplifier. Quantising the raw wall turns a curve into a
    staircase, and a staircase costs the simplifier a node per step - `o` came
    out with MORE nodes, not fewer, and a worse shape.

    A run ends where taking one more node would spread it wider than the
    tolerance, so no node ever moves further than that however long the run.
    The tolerance is INCLUSIVE, and it is measured on the whole units userData
    stores rather than on the fraction underneath: two nodes that read as 5
    apart are 5 apart here, whatever the decimal says.

    The x kept is the OUTERMOST of the run - the smallest, in the space where
    smaller is further out into the whitespace - rather than the mean. Rounding
    a bubble inwards would have it report room the glyph does not have, and the
    unit or two saved by averaging is not worth a pair kerning tighter than the
    outline allows.
    """
    if tolerance <= 0 or len(points) < 3:
        return list(points)

    def flush(run):
        # The ends only: every node between them is on the line they make.
        edge = min(round(x) for x, _ in run)
        return [(edge, run[0][1])] if len(run) == 1 else [(edge, run[0][1]), (edge, run[-1][1])]

    aligned, group = [], []
    for point in points:
        span = group + [point]
        xs = [round(x) for x, _ in span]
        if group and max(xs) - min(xs) > tolerance:
            aligned.extend(flush(group))
            group = [point]
        else:
            group = span
    if group:
        aligned.extend(flush(group))
    return aligned


def snap_points(points, grid_y=0):
    """Round a wall onto the horizontal grid. -> [(int x, int y)]

    Call it in WALL space (smaller x is further out). Where snapping puts two
    nodes on one row the outermost survives, because a bubble that gave up
    ground to rounding would report less whitespace than the glyph has.

    Only the ROWS snap. A bubble node's x is a measurement of whitespace, and
    rounding a measurement to a round number does not make it truer; the height
    it was measured at is the part worth lining up between glyphs.

    A zero increment means no snapping; coordinates are still rounded to
    integers, which is what userData stores either way.
    """
    snapped = []
    for x, y in points:
        if grid_y:
            y = round(y / float(grid_y)) * grid_y
        node = (int(round(x)), int(round(y)))
        if snapped and snapped[-1][1] == node[1]:
            if node[0] < snapped[-1][0]:
                snapped[-1] = node
            continue
        snapped.append(node)
    return snapped


def drop_crowded(points, min_gap):
    """Thin out nodes that sit on top of each other. -> [(int x, int y)]

    Call it LAST. Dropping a node never moves the ones that stay, so a wall
    that was on the grid is still on the grid afterwards, and doing it before
    the simplifier would only hand the simplifier a shape it did not measure.

    THE TWO ENDS STAY. They are where the wall meets the top and bottom of the
    span rather than anything measured, and a wall that stopped short of its
    own extent would report whitespace the glyph has not got. Where the last
    node crowds the end it is the last node that goes.
    """
    if min_gap <= 0 or len(points) < 3:
        return points
    kept = [points[0]]
    for point in points[1:-1]:
        if math.hypot(point[0] - kept[-1][0], point[1] - kept[-1][1]) >= min_gap:
            kept.append(point)
    last = points[-1]
    while len(kept) > 1 and math.hypot(
            last[0] - kept[-1][0], last[1] - kept[-1][1]) < min_gap:
        kept.pop()
    kept.append(last)
    return kept


# --- The grid setting -----------------------------------------------------


# Each setting the file may carry, and the app preference it falls back to.
# The names are the ones a person types into Font Info, so they are short and
# they are the words the panel uses.
SETTING_PREFS = {
    "simplify": PREF_TOLERANCE,
    "bend": PREF_WALL_ANGLE,
    "depth": PREF_MAX_INSET,
    "amplitude": PREF_AMPLITUDE,
    "fit": PREF_FIT,
    "grid": PREF_GRID_Y,
}
SETTING_ORDER = ("simplify", "bend", "depth", "amplitude", "fit", "grid")
# `bend` has been `turn` and `hug` on the way to being named after what it
# does to a wall rather than after the angle it caps. Files written under
# either of the old names still read.
SETTING_ALIASES = {"turn": "bend", "hug": "bend"}


def _tidy(number):
    """4.0 -> '4', 0.5 -> '0.5'. What a person would have typed."""
    return "%g" % float(number)


def parse_settings(value):
    """`"simplify: 4; bend: 40"` -> {"simplify": 4.0, "bend": 40.0}

    Separators are loose on purpose - semicolons, commas and newlines all
    divide, and `:` or `=` both assign - because this is a field someone edits
    by hand in Font Info. An unreadable pair is logged and dropped rather than
    raising: a typo must cost that one setting, not the run.
    """
    if value is None:
        return {}
    text = str(value)
    # A WHOLE PARAMETER OFF THE CLIPBOARD. Glyphs wraps a copied parameter in
    # a plist, and someone pasting that into a text field means the settings
    # inside it, not a plist they have to unwrap by hand first.
    pasted = re.search(r'value\s*=\s*"([^"]*)"', text)
    if pasted is not None and "customParameters" in text:
        text = pasted.group(1)
    settings = {}
    for chunk in re.split(r"[;,\n]+", text):
        if not chunk.strip():
            continue
        parts = re.split(r"[:=]", chunk, 1)
        if len(parts) != 2:
            log("BubbleKern: ignoring %r in %s" % (chunk.strip(), SETTINGS_PARAMETER))
            continue
        key = parts[0].strip().lower()
        key = SETTING_ALIASES.get(key, key)
        if key not in SETTING_PREFS:
            log("BubbleKern: ignoring unknown setting %r" % key)
            continue
        try:
            settings[key] = float(parts[1].strip())
        except ValueError:
            log("BubbleKern: ignoring %s %r" % (key, parts[1].strip()))
    return settings


def format_settings(values):
    """{"depth": 20.0} -> "depth: 20". The order is the panel's, always."""
    return "; ".join("%s: %s" % (key, _tidy(values[key]))
                     for key in SETTING_ORDER if values.get(key) is not None)


def format_parameter(values):
    """The settings as a custom parameter Font Info will take off the clipboard.

    This is the shape Glyphs itself writes when it copies a parameter row, so
    pasting it into Custom Parameters CREATES the parameter - nobody has to
    add one first and then fill it in. Pasting a second time adds a second
    row rather than replacing the first, which is Glyphs' doing, not ours.
    """
    return ('{\ncustomParameters = (\n{\nname = %s;\nvalue = "%s";\n}\n);\n}\n'
            % (SETTINGS_PARAMETER, format_settings(values)))


def _parameter(holder, name):
    """One custom parameter off a font or a master. -> value, or None"""
    if holder is None:
        return None
    try:
        return holder.customParameters[name]
    except Exception:  # a test double, or a holder without the key
        return None


def level_settings(holder):
    """What ONE font or master says. -> {key: float}

    `BubbleKernGrid` still counts, for the files written before there was a
    settings parameter to put the grid in; the parameter wins where both name
    it.
    """
    settings = parse_settings(_parameter(holder, SETTINGS_PARAMETER))
    if "grid" not in settings:
        legacy = _parameter(holder, GRID_PARAMETER)
        if legacy is not None:
            grid = parse_grid(legacy)
            if grid is None:
                log("BubbleKern: ignoring malformed %s %r" % (GRID_PARAMETER, legacy))
            else:
                settings["grid"] = float(grid)
    return settings


def stored_settings(font, master=None):
    """What the FILE says, master over font, key by key. -> {key: float}

    Key by key rather than all or nothing: a master that only wants its own
    depth should say so in one line and take the rest from the font.
    """
    merged = level_settings(font)
    merged.update(level_settings(master))
    return merged


def settings_source(font, master=None):
    """Where the settings in force live. -> "master", "font" or "app"."""
    if _parameter(master, SETTINGS_PARAMETER) is not None:
        return "master"
    if _parameter(font, SETTINGS_PARAMETER) is not None:
        return "font"
    return "app"


def store_settings(holder, values):
    """Write the settings parameter onto a font or a master."""
    if holder is not None:
        holder.customParameters[SETTINGS_PARAMETER] = format_settings(values)


def clear_settings(holder):
    """Take the settings parameter off a font or a master."""
    if holder is None or _parameter(holder, SETTINGS_PARAMETER) is None:
        return
    try:
        del holder.customParameters[SETTINGS_PARAMETER]
    except Exception:
        log("BubbleKern: could not remove %s" % SETTINGS_PARAMETER)


def setting_value(key, font=None, master=None, prefs=None):
    """The value in force for one setting: master, then font, then the app."""
    stored = stored_settings(font, master)
    if key in stored:
        return stored[key]
    return _pref(SETTING_PREFS[key], None, prefs)


def parse_grid(value):
    """`"50"` -> 50. Anything else -> None.

    A two-number `"10 50"` is read as the OLD x/y spelling and its second
    number kept, so a file written before the grid lost its vertical lines
    still snaps to the rows it always did.
    """
    if value is None:
        return None
    parts = [part for part in re.split(r"[\s,]+", str(value).strip()) if part]
    if len(parts) not in (1, 2):
        return None
    try:
        return max(0, int(round(float(parts[-1]))))
    except ValueError:
        return None


def resolve_grid(font, master=None, prefs=None):
    """The row spacing the bubble nodes snap to. -> int, 0 = no snapping.

    The font's `BubbleKernGrid` parameter first, the app preference second,
    off otherwise. The parameter wins because a grid is a property of the
    drawing rather than of the person: 10/50 on a 1000 upm text face means
    something else on a 2048 upm display face, and the file is what remembers
    which one it is. A malformed parameter is logged and ignored rather than
    raising - a typo must not break the tool.
    """
    stored = stored_settings(font, master)
    if "grid" in stored:
        return max(0, int(round(stored["grid"])))
    if not _pref(PREF_GRID_ON, False, prefs):
        return 0
    return max(0, int(_pref(PREF_GRID_Y, 0, prefs) or 0))


def _pref(key, fallback=None, prefs=None):
    """One app preference, with the tests able to pass a plain dict."""
    if prefs is not None:
        value = prefs.get(key)
        return fallback if value is None else value
    try:
        from GlyphsApp import Glyphs
        value = Glyphs.defaults[key]
    except Exception:  # no Glyphs, or no such key
        return fallback
    return fallback if value is None else value


# What the settings sliders offer: (lowest, highest, tick step). One place,
# because the fitter searches the same ranges the window can reach.
# Simplify is a distance in font units, the tolerance the simplifier works to.
# Its default is `step * TOLERANCE_STEPS`, which is 10 units at 1000 upm and
# sits inside this range.
TOLERANCE_RANGE = (0.0, 30.0, 5.0)
ANGLE_RANGE = (30.0, 70.0, 5.0)
INSET_RANGE = (10.0, 50.0, 5.0)
AMPLITUDE_RANGE = (50.0, 100.0, 5.0)
# Fit: air left BETWEEN two bubbles, as a percentage of the em, centred on 0.
# At 0 they touch, which is what a bubble has always meant here. Right of it
# every pair that KERNS opens, left of it every pair that kerns tightens; a
# pair whose walls already touch is left where it is, and nothing is ever
# pushed past 0 into positive kerning. See `with_fit`. This is the knob that
# answers "everything comes out tighter than I kern it".
FIT_RANGE = (-2.0, 2.0, 0.25)
# The smallest kern worth writing, as a percentage of the em. Below it the
# kerner writes nothing: 4 units on a 1000 upm face is not spacing, it is
# noise in the kerning table.
MIN_KERN_RANGE = (0.0, 2.0, 0.25)


def _amount(value, fallback, span=None):
    """A number a SLIDER wrote. -> float

    `_number` reads a typed field, where blank and zero both mean "work it
    out for me". A slider always has a value and 0 is one of them, so this
    reads it straight and only falls back on a preference never set.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if span is not None:
        number = min(span[1], max(span[0], number))
    return number


def _number(value, fallback):
    """A preference a person typed. -> float, or the fallback

    Blank, junk and zero all mean "work it out for me", which is what the
    settings window offers for the gap and the tolerance: both are in font
    units, and a number that suits a 1000 upm text face is the wrong number
    for a 2048 upm display face. Left alone they scale themselves.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def wall_slope(angle):
    """Degrees off vertical -> the slope the wall may recede at.

    Degrees because that is what a designer reads off the drawing: 60 is the
    deep step, 35 is one long diagonal. Clamped to something a wall can
    actually be - at 0 it could never leave the edge, at 90 it could cut
    straight across the glyph.
    """
    angle = _number(angle, WALL_ANGLE)
    return math.tan(math.radians(min(85.0, max(5.0, angle))))


def auto_settings(font, master, prefs=None):
    """Gap, tolerance and node limit for a run. -> dict

    Read from the settings window, so a single glyph regenerated on its own
    comes out the shape a font-wide run would have given it.
    """
    step = raster_step(font)
    stored = stored_settings(font, master)

    def setting(key, fallback, span):
        # The file first, the app second, and either way clamped to the range
        # the slider offers: a parameter is typed by hand and can say 900.
        value = stored.get(key)
        if value is None:
            value = _pref(SETTING_PREFS[key], None, prefs)
        return _amount(value, fallback, span)

    return {
        # The gap is always each side's own sidebearing. It is the calibration
        # that puts a flat pair at zero, not a taste, so there is no knob.
        "gap": None,
        "tolerance": setting("simplify", step * TOLERANCE_STEPS, TOLERANCE_RANGE),
        "max_nodes": DEFAULT_MAX_NODES,
        "slope": wall_slope(setting("bend", WALL_ANGLE, ANGLE_RANGE)),
        # Per cent of the LAYER'S ADVANCE, resolved per glyph in
        # `nodes_from_profile`: a narrow glyph has less room to give away, and
        # one depth in units cannot be right for both it and a wide one.
        "max_inset": setting("depth", MAX_INSET_PERCENT, INSET_RANGE),
        "amplitude": setting("amplitude", 100.0, AMPLITUDE_RANGE) / 100.0,
        # Not a taste either: a tolerance for noise, in units of this em.
        "align": font.upm * ALIGN_EM,
        "step": step,
    }


# --- Putting it together --------------------------------------------------


def nodes_from_profile(profile, side, step, gap, low_y, high_y, width,
                       tolerance, max_nodes=DEFAULT_MAX_NODES, grid=0,
                       slope=WALL_SLOPE, max_inset=None, amplitude=AMPLITUDE,
                       align=0.0, min_gap=0.0):
    """A measured side, ready for userData. -> [(int x, int y)]

    Simplify, then snap, then collapse: snapping first would flatten features
    the simplifier should have been allowed to see, and snapping last is what
    keeps the promise that every node sits on the grid.
    """
    # `max_inset` arrives as a PERCENTAGE of the advance and leaves here in
    # units, which is all `bubble_wall` deals in.
    deepest = None if max_inset is None else width * max_inset / 100.0
    wall = bubble_wall(profile, step, gap, low_y, high_y, max(1.0, width / 2.0), slope, deepest)
    # Flatten BEFORE simplifying, so the simplifier spends its nodes on what is
    # left rather than on detail about to be scaled away.
    wall = flatten_wall(wall, amplitude)
    # Straighten AFTER simplifying, on the nodes it kept: the noise on a flat
    # side costs a node either way, and this is where it can be given back.
    wall = align_columns(simplify(wall, tolerance, max_nodes), align)
    wall = snap_points(wall, grid)
    # AFTER SNAPPING, because snapping is itself a way of putting two nodes
    # within a few units of each other.
    wall = drop_crowded(wall, min_gap)
    if side == RIGHT:
        wall = [(-x, y) for x, y in wall]
    return wall


# --- Fitting the settings to kerning done by hand -------------------------

# The three that SHAPE a wall. Simplify and the node limit spend nodes rather
# than move the wall, and the gap is the calibration rather than a taste.
def _steps_of(span, step=None):
    """Every value a slider's ticks land on. -> (float, ...)"""
    low, high, tick = span
    step = tick if step is None else step
    return tuple(low + step * index
                 for index in range(int(round((high - low) / step)) + 1))


# Label, range and readout for every setting that has a slider, in the order
# they are shown. One table, because the settings window and the Font Info
# sheet both build from it and a range that disagreed between them would be a
# value one of them could not reach.
# THE NUMBER ALONE. What each one means is the label's job, and a sentence
# repeated down five rows is read once and skipped forever after.
# SIMPLIFY IS NOT HERE. It set the tolerance the wall is thinned to, which is
# a number about the node count rather than about the shape - nobody moved it
# looking at a bubble. The engine still takes `simplify:` from a parameter
# typed by hand; it simply has no control of its own any more.
SETTING_UI = (
    ("bend", "Bend", ANGLE_RANGE, "%.0f"),
    ("depth", "Depth", INSET_RANGE, "%.0f"),
    ("amplitude", "Amplitude", AMPLITUDE_RANGE, "%.0f"),
    ("fit", "Fit", FIT_RANGE, "%+.2f"),
)


FIT_ANGLES = _steps_of(ANGLE_RANGE, 10.0)  # every other tick: 5, not 9
FIT_INSETS = _steps_of(INSET_RANGE)
FIT_AMPLITUDES = _steps_of(AMPLITUDE_RANGE, 10.0)  # every other tick: 6, not 11
FIT_PERCENTS = _steps_of(FIT_RANGE)  # PER CENT of the em. `fit_settings` deals
# in units, so a caller scales these by the upm before handing them over.


# --- The pairs worth kerning ----------------------------------------------

# Ranked, best first, from André Fuchs's kerning-pairs (MIT, © 2019 André
# Fuchs): https://github.com/andre-fuchs/kerning-pairs — the pairs that
# actually turn up in running text, counted over a large multi-language
# corpus. Vendored beside this file with its licence.
#
# WHY IT IS WORTH HAVING: a kerning preset here is a CARTESIAN PRODUCT, so
# uppercase against uppercase asks for 676 pairs when most of those two
# letters never stand next to each other in any language. The list says which
# ones do.
RELEVANT_PAIRS_FILE = "kerning-pairs-fuchs.json"
_relevant_pairs = None


def relevant_pairs():
    """Every relevant pair as a two-character string, best first. -> [str]

    Read once and kept: it is a fixed table shipped with the plugin, and the
    kerner asks for it per run.
    """
    global _relevant_pairs
    if _relevant_pairs is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            RELEVANT_PAIRS_FILE)
        try:
            with open(path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except Exception:  # noqa: BLE001 - a missing table is not a crash
            loaded = []
        _relevant_pairs = [pair for pair in loaded
                           if isinstance(pair, str) and len(pair) == 2]
    return _relevant_pairs


def relevant_pair_names(names_by_character, limit=None):
    """The relevant pairs this font can spell, as glyph names. -> {(str, str)}

    `names_by_character` says which glyph draws each character, which is the
    font's business; the list is this module's. A pair whose either half the
    font has no glyph for is dropped rather than guessed at.
    """
    pairs = relevant_pairs()
    if limit:
        pairs = pairs[:limit]
    named = set()
    for pair in pairs:
        left = names_by_character.get(pair[0])
        right = names_by_character.get(pair[1])
        if left is not None and right is not None:
            named.add((left, right))
    return named


def fit_space(font, master=None, prefs=None):
    """The air to leave between two bubbles, in units. -> float"""
    value = setting_value("fit", font, master, prefs)
    return font.upm * _amount(value, 0.0, FIT_RANGE) / 100.0


def min_kern(font, prefs=None):
    """The smallest kern the kerner will write, in units. -> float"""
    return font.upm * _amount(_pref(PREF_MIN_KERN, None, prefs), 0.5, MIN_KERN_RANGE) / 100.0


def kern_from_walls(right_nodes, left_nodes):
    """What two generated walls ask for between them. -> float, or None

    Negative tightens, which is the sign the kerner writes and the sign the
    font stores. Both walls are polylines, so their closest approach is at a
    vertex of one or the other: reading every node height of both is exact,
    not a sample.

    None where the two never share a height, which is a pair no bubble can
    decide - `period` against a cap, and every accent against a baseline mark.
    """
    if not right_nodes or not left_nodes:
        return None
    closest = None
    for y in sorted({y for _, y in right_nodes} | {y for _, y in left_nodes}):
        rights, lefts = xs_at(right_nodes, y), xs_at(left_nodes, y)
        if not rights or not lefts:
            continue
        # A right wall is stored relative to the advance, so its sign is
        # already flipped: -x is the whitespace that side claims.
        clearance = min(-right + left for right in rights for left in lefts)
        if closest is None or clearance < closest:
            closest = clearance
    return None if closest is None else -closest


def with_fit(kern, space):
    """A generated kern, moved by Fit. -> float

    Fit only moves pairs that ALREADY kern. A pair whose walls touch is at
    the spacing the file gave it, and neither loosening nor tightening the fit
    is an instruction to change that - it is what keeps a flat pair at zero.

    And it never pushes a pair past 0 into positive kerning: a bubble that
    cannot reach its neighbour is asking for nothing, not for room.
    """
    if kern >= 0 or not space:
        return kern
    return min(0.0, kern + space)


def fit_settings(profiles, geometry, targets, step, tolerance,
                 max_nodes=DEFAULT_MAX_NODES, grid=0, angles=FIT_ANGLES,
                 insets=FIT_INSETS, amplitudes=FIT_AMPLITUDES, spaces=(0.0,),
                 align=0.0, progress=None):
    """The wall parameters that come closest to kerning done by hand.

    `targets` is [(left name, right name, value)] as the font stores it.
    -> {"angle", "inset", "amplitude", "error", "pairs", "unreachable",
        "misses": [(left, right, wanted, generated)]}  or None

    A grid search, because the space is three small dimensions and what is
    being searched is not smooth: the inset cap is a clamp and the turn angle
    is a limit, and either can do nothing at all over a whole range and then
    decide everything one step later. A gradient would fall down that.

    Measuring is done ONCE, by the caller, before any of this: it is by far
    the expensive part and no parameter here changes it.
    """
    usable = [
        (left, right, float(value)) for left, right, value in targets
        if left in profiles and right in profiles
    ]
    if not usable:
        return None
    gaps = {name: layer_gap(sides) for name, sides in profiles.items()}
    # A wall never leaves its own advance, so a generated pair can only ever
    # tighten. A designer's POSITIVE kern is out of the model's reach and no
    # combination will fit it; it is counted so the caller can say so.
    unreachable = sum(1 for _, _, value in usable if value > 0)
    best = None
    total = len(angles) * len(insets) * len(amplitudes)
    done = 0
    for angle in angles:
        slope = wall_slope(angle)
        for inset in insets:
            # Only the angle and the cap reach `bubble_wall`; the amplitude
            # and the simplifier work on what it returns, so the walls are
            # built once per pair of them rather than once per combination.
            raw = {}
            for name, sides in profiles.items():
                low_y, high_y, width = geometry[name]
                for side in (LEFT, RIGHT):
                    raw[(name, side)] = bubble_wall(
                        sides[side], step, gaps[name], low_y, high_y,
                        max(1.0, width / 2.0), slope, width * inset / 100.0)
            for amplitude in amplitudes:
                nodes = {}
                for key, wall in raw.items():
                    if not wall:
                        nodes[key] = []
                        continue
                    shaped = snap_points(
                        align_columns(
                            simplify(flatten_wall(wall, amplitude / 100.0), tolerance, max_nodes),
                            align),
                        grid)
                    nodes[key] = [(-x, y) for x, y in shaped] if key[1] == RIGHT else shaped
                base = []
                for left, right, value in usable:
                    generated = kern_from_walls(nodes[(left, RIGHT)], nodes[(right, LEFT)])
                    if generated is not None:
                        base.append((left, right, value, generated))
                done += 1
                if progress is not None:
                    progress(done, total)
                if not base:
                    continue
                # Minimum space only SHIFTS what the walls decided, so every
                # value of it is scored off the one set of walls.
                for space in spaces:
                    # Scored without building anything: this inner loop runs
                    # once per combination per space, and a list per pass cost
                    # more than the whole search did.
                    score = sum(abs(with_fit(generated, space) - value)
                                for _, _, value, generated in base) / len(base)
                    if best is None or score < best["error"]:
                        best = {
                            "angle": angle, "inset": inset, "amplitude": amplitude,
                            "space": space, "error": score, "pairs": len(base),
                            "unreachable": unreachable,
                            "misses": [(left, right, value, with_fit(generated, space))
                                       for left, right, value, generated in base],
                        }
    return best


def measurable(glyph, layer):
    """Is this a glyph whose bubble we should draw at all? -> bool

    Marks are nonspacing, so no neighbour is ever spaced against them, and a
    composite already inherits its bubble from its components through
    `gatherBubbleInfo` - generating one would override that with a worse copy.
    """
    if not glyph.export or glyph.category == "Mark" or glyph.subCategory == "Nonspacing":
        return False
    if layer is None:
        return False
    if not len(layer.paths) and len(layer.components):
        return False
    return True


def collect_sides(font, master, step, progress=None):
    """Measure one master. -> ({LEFT: {name: profile}, RIGHT: ...}, geometry)

    `geometry` is {name: (low_y, high_y, width)}, kept from the same pass so
    building the walls afterwards does not scan the font a second time.
    """
    sides = {LEFT: {}, RIGHT: {}}
    geometry = {}
    total = len(font.glyphs)
    for index, glyph in enumerate(font.glyphs):
        if progress is not None and index % 10 == 0:
            progress(index, total)
        layer = glyph.layers[master.id]
        if not measurable(glyph, layer):
            continue
        scanned = scan_layer(layer, step, skip_marks=True)
        if scanned is None:
            continue
        rows = scanned[0]
        if len(rows) < MIN_ROWS_TO_MEASURE:
            continue
        measured = kern_profiles(rows, layer.width, step)
        for side in (LEFT, RIGHT):
            sides[side][glyph.name] = measured[side]
        low_y, high_y = layer_span(layer, master)
        geometry[glyph.name] = (low_y, high_y, layer.width)
    return sides, geometry


def auto_bubble_plan(font, master, gap=None, step=None, tolerance=None,
                     max_nodes=DEFAULT_MAX_NODES, grid=0,
                     tolerance_em=GROUP_TOL_EM, sides=(LEFT, RIGHT),
                     slope=WALL_SLOPE, max_inset=None, amplitude=AMPLITUDE,
                     align=None, progress=None):
    """Everything a font-wide run would write, decided before anything is.

    -> {side: {"nodes": {glyph: [(x, y)]}, "refer": {member: representative}}}

    A cluster's representative gets a bubble built from ITS OWN profile rather
    than the group medoid's, so its drawing is honest about its own shape;
    every member of the cluster is within tolerance of every other, which is
    what `cluster_kern_side` enforces, so any of them would serve.
    """
    if step is None:
        step = raster_step(font)
    if tolerance is None:
        tolerance = step * TOLERANCE_STEPS
    if max_inset is None:
        max_inset = MAX_INSET_PERCENT
    if align is None:
        align = font.upm * ALIGN_EM
    measured, geometry = collect_sides(font, master, step, progress)
    group_tolerance = font.upm * tolerance_em
    plan = {}
    for side in sides:
        profiles = measured[side]
        groups = cluster_kern_side(profiles, group_tolerance, step)
        refer = {
            member: representative
            for representative, members in groups.items()
            for member in members
            if member != representative
        }
        nodes = {}
        for name, profile in profiles.items():
            if name in refer:
                continue
            low_y, high_y, width = geometry[name]
            this_gap = gap
            if this_gap is None:
                this_gap = layer_gap({s: measured[s][name] for s in (LEFT, RIGHT)})
            nodes[name] = nodes_from_profile(
                profile, side, step, this_gap, low_y, high_y, width,
                tolerance, max_nodes, grid, slope, max_inset, amplitude,
                align, font.upm * MIN_GAP_EM,
            )
        plan[side] = {"nodes": nodes, "refer": refer}
    return plan


def auto_bubble_nodes(layer, side, gap=None, step=None, tolerance=None,
                      max_nodes=DEFAULT_MAX_NODES, grid=0, slope=WALL_SLOPE,
                      max_inset=None, amplitude=AMPLITUDE, align=None):
    """One side of one layer. -> [(int x, int y)], or None if unmeasurable."""
    font = layer.font()
    master = layer.associatedFontMaster()
    if step is None:
        step = raster_step(font)
    if tolerance is None:
        tolerance = step * TOLERANCE_STEPS
    if max_inset is None:
        max_inset = MAX_INSET_PERCENT
    if align is None:
        align = font.upm * ALIGN_EM
    # ACCENTS INCLUDED, unlike the kerning measurement. A drawn bubble has to
    # agree with `layer_span`, which takes the layer's WHOLE bounding box - so
    # leaving the marks out gave a wall that ran up over the accent's rows with
    # no ink to follow, coned inward, hit the inset clamp and came down as a
    # straight line through the middle of the circumflex. Either end of that
    # disagreement would close it; this is the end that keeps a bubble a
    # picture of the glyph you can see.
    scanned = scan_layer(layer, step)
    if scanned is None:
        return None
    rows = scanned[0]
    if len(rows) < MIN_ROWS_TO_MEASURE:
        return None
    profiles = kern_profiles(rows, layer.width, step)
    if gap is None:
        gap = layer_gap(profiles)
    profile = profiles[side]
    low_y, high_y = layer_span(layer, master)
    return nodes_from_profile(
        profile, side, step, gap, low_y, high_y, layer.width,
        tolerance, max_nodes, grid, slope, max_inset, amplitude, align,
        font.upm * MIN_GAP_EM,
    )
