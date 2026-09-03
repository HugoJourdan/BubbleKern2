"""The bubble maths, on synthetic profiles that stand in for real glyphs.

Row indices are scanlines on the shared grid: at a step of 10 units and a
1000 upm em, lowercase runs roughly rows 0-50 and caps reach 70. Depth is
measured inward from the origin and from the advance, so a straight stem is
its sidebearing at every row and a bowl swells toward the middle of its band.

    python3 -m pytest -q
"""

from __future__ import annotations

import importlib.util
import math
import pathlib
import sys
from types import SimpleNamespace

import pytest

MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "PolyKernCentral.glyphsPlugin/Contents/Resources/PKAutoBubble.py"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# UNDER ITS REAL NAME, so `PKAutoBubble` finds it by a plain import - and by
# sys.modules rather than sys.path, which would also put `PKCommonLogic` in
# reach and swap this module's no-op `log` for one that writes to the Desktop.
_load("PKSide", MODULE_PATH.parent / "PKSide.py")
pk = _load("pk_auto_bubble", MODULE_PATH)

LEFT, RIGHT = pk.LEFT, pk.RIGHT


def flat(rows, value):
    return {row: float(value) for row in rows}


# One row's worth of recession at the wall's own slope, which is what every
# cone assertion below is measured in.
RISE = pk.WALL_SLOPE * 10


def wall_at(wall):
    """The wall as {y: x}, which is how every assertion below reads it."""
    return {y: x for x, y in wall}


# --- The wall -------------------------------------------------------------


def test_a_straight_side_gives_a_straight_wall_one_gap_out():
    """A stem is its sidebearing at every row, so its wall is a straight line
    that far out and no further."""
    wall = wall_at(pk.bubble_wall(flat(range(0, 10), 30.0), 10, 25.0, 0, 95, 500))
    assert {wall[(row + 0.5) * 10] for row in range(0, 10)} == {5.0}


def test_the_wall_opens_where_the_ink_recedes():
    """`T`: the arm sits near the edge, the stem is far behind it, and the
    wall has to follow the recession or nothing can tuck under the arm."""
    profile = dict(flat(range(0, 5), 200.0))   # stem, deeply recessed
    profile.update(flat(range(5, 10), 20.0))   # arm, out at the edge
    wall = wall_at(pk.bubble_wall(profile, 10, 0.0, 0, 95, 1000))
    assert wall[95] == pytest.approx(20.0)             # out at the arm
    assert wall[5] == pytest.approx(20.0 + RISE * 5)   # and back at the stem
    # Not the stem's own 200: a neighbour cannot reach into a recession at an
    # arbitrary angle, so the wall recedes at the slope and no faster. That
    # clamp is what keeps a `P` from drawing a deep step under its bowl.


def test_the_wall_recedes_along_the_cone_past_the_ink():
    """Nothing is drawn below the baseline of an `o`, but a descender coming
    up at it still meets something - the cone, not a cliff."""
    wall = wall_at(pk.bubble_wall(flat(range(0, 10), 30.0), 10, 0.0, -100, 95, 5000))
    assert wall[5] == pytest.approx(30.0)
    assert wall[-5] == pytest.approx(30.0 + RISE)     # one row down, one rise
    assert wall[-95] == pytest.approx(30.0 + RISE * 10)


def test_a_hole_inside_the_band_does_not_blow_the_wall_open():
    """`equal`: two bars with a gap between them. The frontier in the gap is
    the cone from the BARS, a few units in - not the hundreds that the
    constant-time `cone_depth` reports there.
    """
    profile = dict(flat(range(0, 4), 40.0))
    profile.update(flat(range(8, 12), 40.0))
    wall = wall_at(pk.bubble_wall(profile, 10, 0.0, 0, 115, 5000))
    assert wall[55] == pytest.approx(40.0 + RISE * 2)   # two rows from a bar
    assert wall[55] < 100                                # not off in the weeds


def test_the_wall_clamps_at_max_depth():
    wall = wall_at(pk.bubble_wall(flat(range(0, 10), 900.0), 10, 0.0, 0, 95, 250))
    assert set(wall.values()) == {250.0}


def test_the_two_sides_are_one_wall_negated():
    """Left x is absolute from the origin, right x is relative to the advance,
    so the same measurement stores as its own negation."""
    profile = flat(range(0, 10), 30.0)
    common = dict(step=10, gap=25.0, low_y=0, high_y=95, width=500,
                  tolerance=1.0, max_nodes=12)
    left = pk.nodes_from_profile(profile, LEFT, **common)
    right = pk.nodes_from_profile(profile, RIGHT, **common)
    assert [(-x, y) for x, y in left] == right


def test_a_wall_stays_inside_the_advance_while_the_ink_does():
    """A glyph spaced tighter than the gap would put `depth - gap` outside its
    own sidebearing, claiming whitespace it has not been given."""
    wall = pk.bubble_wall(flat(range(0, 10), 20.0), 10, gap=60.0,
                          low_y=0, high_y=95, max_depth=500)
    assert all(x >= 0 for x, _ in wall)


def test_a_wall_follows_ink_that_has_left_the_advance():
    """`f` and `j` hang a hook or a tail over the edge, and are given a
    negative sidebearing for it. Held at the advance there, the hook would
    stick out of its own bubble and nothing kerning against the glyph could
    see the part of it that reaches furthest."""
    profile = dict(flat(range(0, 5), 20.0))     # the body, inside the advance
    profile.update(flat(range(5, 10), -30.0))   # the hook, 30 units past it
    wall = pk.bubble_wall(profile, 10, gap=60.0,
                          low_y=0, high_y=95, max_depth=500)
    depths = [x for x, _ in wall]
    assert min(depths) == pytest.approx(-30.0)  # out to the ink, and no further
    assert wall_at(wall)[95] == pytest.approx(-30.0)   # the hook's own row


def test_nodes_never_end_up_on_top_of_each_other():
    """A pair four units apart is a node's worth of cost for none of a node's
    worth of shape: nothing in the kerning can see four units, and nobody
    editing the wall by hand can grab one of them without grabbing the other."""
    gap = 1000 * pk.MIN_GAP_EM                  # 10 units at 1000 upm
    crowded = [(-13, -60), (-13, -16), (-13, -12), (-20, 40), (-13, 120)]
    thinned = pk.drop_crowded(crowded, gap)
    assert (-13, -12) not in thinned            # the one that crowded its neighbour
    assert all(math.hypot(a[0] - b[0], a[1] - b[1]) >= gap
               for a, b in zip(thinned, thinned[1:]))
    # THE ENDS ARE NOT NEGOTIABLE: they are the extent of the wall, and a wall
    # stopping short of its own extent reports whitespace the glyph has not got.
    assert thinned[0] == crowded[0] and thinned[-1] == crowded[-1]
    assert pk.drop_crowded([(-13, 0), (-13, 4), (-13, 8)], gap) == [(-13, 0), (-13, 8)]


def test_a_wall_with_room_between_its_nodes_is_left_alone():
    roomy = [(-13, 0), (-13, 50), (-13, 100)]
    assert pk.drop_crowded(roomy, 1000 * pk.MIN_GAP_EM) == roomy


def test_the_relevant_pair_table_is_pairs():
    """Shipped beside the module, so a bad read is a silent empty kerner
    rather than a crash - which makes it worth asserting it is really here."""
    pairs = pk.relevant_pairs()
    assert len(pairs) > 3000
    assert all(isinstance(pair, str) and len(pair) == 2 for pair in pairs)
    assert pairs[0] != pairs[-1]              # ranked, not a set that got sorted


def test_relevant_pairs_are_named_by_what_the_font_can_spell():
    names = {"A": "A", "V": "V", "T": "T", " ": "space"}
    found = pk.relevant_pair_names(names)
    assert ("A", "V") in found
    # THE FONT DECIDES: nothing is invented for a character it cannot draw.
    assert all(left in names.values() and right in names.values()
               for left, right in found)
    assert any(right == "space" or left == "space" for left, right in found)


def test_the_limit_takes_the_top_of_the_ranking():
    names = {chr(code): chr(code) for code in range(0x20, 0x7f)}
    names.update({character: character for character in "ËëÄÖÜáéíóú"})
    everything = pk.relevant_pair_names(names)
    top = pk.relevant_pair_names(names, limit=50)
    assert 0 < len(top) < len(everything)
    assert top <= everything


def test_the_inset_cap_bounds_how_deep_a_wall_goes():
    """The turn angle limits how FAST a wall cuts in and says nothing about how
    far, so a long diagonal follows the ink all the way. The cap is what makes
    it run vertical instead, which is what a designer draws there."""
    # 5 units of recession per row is well inside the turn the wall is allowed,
    # so the slope never binds here and the cap is the only thing that does.
    diagonal = {row: float(row * 5) for row in range(0, 40)}
    uncapped = pk.bubble_wall(diagonal, 10, 0.0, 0, 395, 5000)
    capped = pk.bubble_wall(diagonal, 10, 0.0, 0, 395, 5000, max_inset=85.0)
    assert max(x for x, _ in uncapped) == pytest.approx(195.0)
    assert max(x for x, _ in capped) == pytest.approx(85.0)
    assert min(x for x, _ in capped) >= 0


def test_the_default_gap_is_the_layer_s_larger_sidebearing():
    """The calibration, stated as the kerner states it:

        kern = gap_A + gap_B - min(depth_right_of_A + depth_left_of_B)

    A profile is depth measured inward, so its minimum is that side's
    sidebearing: read the gap off the LAYER and any flat pair comes out at 0,
    however the font is spaced.
    """
    rows = [(row + 0.5) * 10 for row in range(0, 10)]

    def kern(right_of_a, left_of_b, gap_a, gap_b):
        right = wall_at(pk.bubble_wall(right_of_a, 10, gap_a, 0, 95, 500, slope=100.0))
        left = wall_at(pk.bubble_wall(left_of_b, 10, gap_b, 0, 95, 500, slope=100.0))
        return -min(left[y] + right[y] for y in rows)

    for sidebearing in (12.0, 45.0, 120.0):  # spaced nothing like each other
        flat_side = flat(range(0, 10), sidebearing)
        gap = pk.layer_gap({pk.LEFT: flat_side, pk.RIGHT: flat_side})
        assert gap == sidebearing
        assert kern(flat_side, flat_side, gap, gap) == pytest.approx(0.0)


def test_the_larger_sidebearing_holds_where_each_side_s_own_would_not():
    """An `l`: the flag reaches 16 further left than the foot, so the glyph's
    two extremes sit at DIFFERENT heights. Each side's own sidebearing would
    put every wall on its own edge and still leave the pair tightening by 16,
    because no single row has both walls on theirs. The larger sidebearing
    lets the clamp take over on the tighter side, and `l|l` comes out at 0 -
    which is what its hand-drawn bubble gives.
    """
    left = flat(range(0, 5), 34.0)    # foot
    left.update(flat(range(5, 10), 18.0))   # flag, further out
    right = flat(range(0, 5), 34.0)   # foot
    right.update(flat(range(5, 10), 60.0))  # stem, further in
    rows = [(row + 0.5) * 10 for row in range(0, 10)]

    def kern(gap_left, gap_right):
        wall_l = wall_at(pk.bubble_wall(left, 10, gap_left, 0, 95, 500, slope=100.0))
        wall_r = wall_at(pk.bubble_wall(right, 10, gap_right, 0, 95, 500, slope=100.0))
        return -min(wall_l[y] + wall_r[y] for y in rows)

    assert pk.layer_gap({pk.LEFT: left, pk.RIGHT: right}) == 34.0
    assert kern(34.0, 34.0) == pytest.approx(0.0)
    assert kern(18.0, 34.0) == pytest.approx(-16.0)  # each side's own


def test_the_wall_never_turns_harder_than_the_slope_allows():
    """The deep step: below the bowl of a `P` the side falls away 300 units in
    130, and at 60 degrees off vertical the wall is allowed to dive after it.
    At 35 it takes one long diagonal instead."""
    profile = dict(flat(range(0, 20), 300.0))   # stem, far in
    profile.update(flat(range(20, 40), 20.0))   # bowl, out at the edge
    for angle, step in ((60.0, 10), (35.0, 10)):
        slope = pk.wall_slope(angle)
        wall = pk.bubble_wall(profile, step, 0.0, 0, 395, 1000, slope)
        worst = max(
            abs(x1 - x0) / (y1 - y0)
            for (x0, y0), (x1, y1) in zip(wall, wall[1:]) if y1 > y0
        )
        assert worst <= slope + 1e-6


def test_the_wall_angle_is_read_in_degrees_and_clamped():
    assert pk.wall_slope(45) == pytest.approx(1.0)
    assert pk.wall_slope("") == pytest.approx(pk.WALL_SLOPE)   # blank = default
    assert pk.wall_slope(0) == pytest.approx(pk.WALL_SLOPE)       # 0 reads as blank
    assert pk.wall_slope(1) == pytest.approx(pk.wall_slope(5))    # never vertical-only
    assert pk.wall_slope(120) == pytest.approx(pk.wall_slope(85))  # never sideways


def test_amplitude_flattens_toward_the_outermost_point():
    """Never toward the mean: that would push the widest part of the wall
    INWARD, behind the ink, and a bubble that no longer contains its own glyph
    lets a pair collide. Toward the outermost, every value only shrinks."""
    wall = [(10.0, 0.0), (50.0, 100.0), (30.0, 200.0)]
    assert pk.flatten_wall(wall, 1.0) == wall
    assert pk.flatten_wall(wall, 0.5) == [(10.0, 0.0), (30.0, 100.0), (20.0, 200.0)]
    assert pk.flatten_wall(wall, 0.0) == [(10.0, 0.0), (10.0, 100.0), (10.0, 200.0)]


def test_flattening_never_moves_a_wall_inward():
    wall = [(10.0, 0.0), (50.0, 100.0), (30.0, 200.0)]
    for amplitude in (0.0, 0.25, 0.5, 0.75):
        flattened = pk.flatten_wall(wall, amplitude)
        assert all(new <= old for (new, _), (old, _) in zip(flattened, wall))
        assert min(x for x, _ in flattened) == pytest.approx(10.0)


# --- Simplification -------------------------------------------------------


def test_a_straight_wall_collapses_to_its_two_ends():
    straight = [(0.0, float(y)) for y in range(0, 200, 5)]
    assert pk.simplify(straight, 1.0) == [(0.0, 0.0), (0.0, 195.0)]


def test_simplification_keeps_the_ends_and_the_corner():
    corner = [(0.0, 0.0), (0.0, 50.0), (100.0, 100.0), (200.0, 150.0)]
    thinned = pk.simplify(corner, 1.0)
    assert thinned[0] == (0.0, 0.0) and thinned[-1] == (200.0, 150.0)
    assert (0.0, 50.0) in thinned


def test_the_node_limit_holds_however_noisy_the_wall():
    noisy = [(float((row * 37) % 23), float(row * 5)) for row in range(150)]
    thinned = pk.simplify(noisy, 1.0, max_nodes=8)
    assert 2 <= len(thinned) <= 8
    assert thinned[0] == noisy[0] and thinned[-1] == noisy[-1]


# --- Aligning ------------------------------------------------------------


def test_a_run_of_near_equal_x_becomes_one_straight_edge():
    """A flat side kept at 33, 32, 31 is a straight edge with a unit of noise
    on it, spending three nodes and two kinks on the unit."""
    wall = [(54.0, 452.0), (33.0, 398.0), (32.0, 338.0), (31.0, 118.0)]
    assert pk.align_columns(wall, 5.0) == [(54, 452.0), (31, 398.0), (31, 118.0)]


def test_the_run_aligns_outwards_not_to_the_average():
    """Smaller x is further out into the whitespace. Rounding a bubble inwards
    would have it report room the glyph does not have."""
    wall = [(20.0, 0.0), (24.0, 50.0), (22.0, 100.0)]
    assert pk.align_columns(wall, 5.0) == [(20, 0.0), (20, 100.0)]


def test_a_slow_drift_is_broken_into_runs_so_no_node_moves_far():
    """A chain of one-unit steps must not walk the wall across the glyph: a
    run ends where taking one more node would spread it past the tolerance."""
    wall = [(float(40 - index), float(index * 10)) for index in range(12)]
    aligned = pk.align_columns(wall, 5.0)
    assert [x for x, _ in aligned] == [35, 35, 29, 29]
    assert [y for _, y in aligned] == [0.0, 50.0, 60.0, 110.0]


def test_the_tolerance_is_inclusive_and_reads_whole_units():
    """A pair that reads as 5 apart on screen is 5 apart to this, whatever the
    fraction underneath says: the wall is stored in whole units."""
    exact = [(28.0, 0.0), (33.0, 50.0), (30.0, 100.0)]
    assert pk.align_columns(exact, 5.0) == [(28, 0.0), (28, 100.0)]
    fractional = [(28.2, 0.0), (33.4, 50.0), (30.0, 100.0)]
    assert pk.align_columns(fractional, 5.0) == [(28, 0.0), (28, 100.0)]


def test_a_zero_tolerance_aligns_nothing():
    wall = [(33.0, 0.0), (32.0, 50.0), (31.0, 100.0)]
    assert pk.align_columns(wall, 0) == wall


def test_a_curve_keeps_its_nodes():
    """It runs on what the simplifier KEPT, and what it keeps on a curve is
    nodes further apart than this. Quantising the raw wall would staircase it
    and cost a node per step."""
    arc = [(0.0, 0.0), (12.0, 100.0), (20.0, 200.0), (26.0, 300.0)]
    assert pk.align_columns(arc, 5.0) == arc


# --- Snapping -------------------------------------------------------------


def test_snapping_rounds_the_rows_and_leaves_the_measurement_alone():
    assert pk.snap_points([(247.4, 683.0), (12.0, 121.0)], 50) == [
        (247, 700), (12, 100),
    ]


def test_a_zero_increment_snaps_nothing_but_still_rounds():
    assert pk.snap_points([(247.4, 683.4)], 0) == [(247, 683)]


def test_nodes_landing_on_one_row_keep_the_outermost():
    """Two rows snapping together must not cost the bubble any width: in wall
    space the smaller x is the one further out into the whitespace."""
    assert pk.snap_points([(40.0, 690.0), (10.0, 710.0)], 50) == [(10, 700)]


# --- Walls of more than one piece ------------------------------------------


def test_one_wall_passes_straight_through():
    wall = [(0.0, 0.0), (10.0, 100.0)]
    assert pk.union_walls([wall]) == wall


def test_the_union_takes_the_outermost_at_every_row():
    """Two components over the same rows: whichever reaches further out is
    what a neighbour meets."""
    base = [(50.0, 0.0), (50.0, 100.0)]
    accent = [(20.0, 0.0), (80.0, 100.0)]
    assert pk.union_walls([base, accent], keep_min=True) == [(20.0, 0.0), (50.0, 100.0)]
    assert pk.union_walls([base, accent], keep_min=False) == [(50.0, 0.0), (80.0, 100.0)]


def test_a_gap_between_the_pieces_is_bridged_not_invented():
    """`Aacute`: the acute floats above the A. Rows in between belong to
    neither, so the wall runs straight from one to the other rather than
    claiming ink that is not there."""
    base = [(30.0, 0.0), (10.0, 500.0)]
    accent = [(60.0, 700.0), (60.0, 800.0)]
    merged = pk.union_walls([base, accent], keep_min=True)
    assert merged == [(30.0, 0.0), (10.0, 500.0), (60.0, 700.0), (60.0, 800.0)]
    assert [y for _, y in merged] == sorted(y for _, y in merged)


def test_a_row_only_one_piece_reaches_uses_that_piece():
    base = [(30.0, 0.0), (30.0, 500.0)]
    accent = [(60.0, 400.0), (60.0, 800.0)]
    merged = dict((y, x) for x, y in pk.union_walls([base, accent], keep_min=True))
    assert merged[800.0] == 60.0     # only the accent is up there
    assert merged[400.0] == 30.0     # both reach; the base is further out
    assert merged[0.0] == 30.0


def test_xs_at_reads_a_horizontal_run_at_both_ends():
    wall = [(10.0, 0.0), (40.0, 0.0), (40.0, 100.0)]
    # The shared vertex is reported twice, once per segment. Harmless: the
    # union only ever takes a min or a max of these.
    assert sorted(set(pk.xs_at(wall, 0.0))) == [10.0, 40.0]
    assert pk.xs_at(wall, 200.0) == []


# --- Agreeing across masters ----------------------------------------------


# --- The grid setting -----------------------------------------------------
class FakeFont:
    def __init__(self, parameter=None, settings=None):
        self.customParameters = {pk.GRID_PARAMETER: parameter}
        if settings is not None:
            self.customParameters[pk.SETTINGS_PARAMETER] = settings
        self.upm = 1000


def test_the_font_parameter_beats_the_preference():
    prefs = {pk.PREF_GRID_ON: True, pk.PREF_GRID_Y: 4}
    assert pk.resolve_grid(FakeFont("50"), prefs=prefs) == 50


def test_the_old_two_number_parameter_keeps_its_rows():
    """`10 50` was x and y. The vertical lines are gone; the rows it asked for
    are still the rows that file snaps to."""
    prefs = {pk.PREF_GRID_ON: True, pk.PREF_GRID_Y: 4}
    assert pk.resolve_grid(FakeFont("10 50"), prefs=prefs) == 50
    assert pk.resolve_grid(FakeFont("10,50"), prefs=prefs) == 50


def test_a_zero_parameter_turns_the_grid_off_for_that_font():
    prefs = {pk.PREF_GRID_ON: True, pk.PREF_GRID_Y: 4}
    assert pk.resolve_grid(FakeFont("0"), prefs=prefs) == 0
    assert pk.resolve_grid(FakeFont("0 0"), prefs=prefs) == 0


def test_a_malformed_parameter_falls_through_to_the_preference():
    prefs = {pk.PREF_GRID_ON: True, pk.PREF_GRID_Y: 4}
    assert pk.resolve_grid(FakeFont("ten by fifty"), prefs=prefs) == 4
    assert pk.resolve_grid(FakeFont("10 20 30"), prefs=prefs) == 4


def test_no_parameter_and_no_preference_means_no_grid():
    assert pk.resolve_grid(FakeFont(None), prefs={}) == 0
    assert pk.resolve_grid(FakeFont(None), prefs={pk.PREF_GRID_ON: False}) == 0


# --- The settings parameter ------------------------------------------------


def test_a_parameter_is_read_the_way_a_person_would_type_it():
    assert pk.parse_settings("simplify: 4; bend: 40; depth: 20") == {
        "simplify": 4.0, "bend": 40.0, "depth": 20.0,
    }
    # Commas, newlines and `=` are all fair: this is a field edited by hand.
    assert pk.parse_settings("fit = -0.5,\ngrid=20") == {"fit": -0.5, "grid": 20.0}


def test_a_file_written_under_an_older_name_still_reads():
    # The setting was named after the angle it caps (`turn`), then after what
    # that angle does to the wall (`hug`), before being named after what it
    # does to the drawing. A parameter typed under either is not a typo.
    assert pk.parse_settings("turn: 40; depth: 20") == {"bend": 40.0, "depth": 20.0}
    assert pk.parse_settings("hug: 40; depth: 20") == {"bend": 40.0, "depth": 20.0}


def test_a_typo_costs_that_setting_and_nothing_else():
    assert pk.parse_settings("depth: 20; bend: forty; wobble: 3; junk") == {"depth": 20.0}
    assert pk.parse_settings(None) == {}


def test_writing_and_reading_a_parameter_round_trips():
    values = {"simplify": 4.0, "bend": 40.0, "depth": 20.0,
              "amplitude": 75.0, "fit": 0.5, "grid": 20.0}
    written = pk.format_settings(values)
    assert written == "simplify: 4; bend: 40; depth: 20; amplitude: 75; fit: 0.5; grid: 20"
    assert pk.parse_settings(written) == values


def test_the_clipboard_form_is_a_whole_parameter_glyphs_will_paste():
    # The shape Glyphs itself writes when it copies a parameter row, so that
    # pasting into Custom Parameters MAKES the row instead of erroring.
    values = {"simplify": 4.0, "bend": 40.0, "depth": 20.0,
              "amplitude": 75.0, "fit": 0.5, "grid": 20.0}
    written = pk.format_parameter(values)
    assert written == (
        "{\ncustomParameters = (\n{\nname = PolyKern;\n"
        'value = "simplify: 4; bend: 40; depth: 20; amplitude: 75; fit: 0.5; grid: 20";\n'
        "}\n);\n}\n")
    # And it still reads back as settings, for a text field at the other end.
    assert pk.parse_settings(written) == values


def test_a_pasted_parameter_is_not_mistaken_for_a_setting_named_value():
    assert pk.parse_settings('{\ncustomParameters = (\n{\nname = PolyKern;\n'
                             'value = "depth: 30";\n}\n);\n}\n') == {"depth": 30.0}


def test_a_master_beats_the_font_setting_by_setting():
    font = FakeFont(settings="depth: 20; bend: 40")
    master = FakeFont(settings="depth: 30")
    assert pk.stored_settings(font, master) == {"depth": 30.0, "bend": 40.0}
    assert pk.stored_settings(font) == {"depth": 20.0, "bend": 40.0}


def test_the_source_is_the_highest_level_holding_a_parameter():
    font, master = FakeFont(settings="depth: 20"), FakeFont(settings="depth: 30")
    assert pk.settings_source(font, master) == "master"
    assert pk.settings_source(font, FakeFont()) == "font"
    assert pk.settings_source(FakeFont(), FakeFont()) == "app"


def test_a_stored_setting_beats_the_preference_and_is_clamped():
    prefs = {pk.PREF_MAX_INSET: 15}
    font = FakeFont(settings="depth: 30")
    assert pk.setting_value("depth", font, prefs=prefs) == 30.0
    assert pk.setting_value("depth", FakeFont(), prefs=prefs) == 15
    # Typed by hand, so it can say anything; the range is what it gets.
    settings = pk.auto_settings(font=FakeFont(settings="depth: 900"),
                                master=None, prefs=prefs)
    assert settings["max_inset"] == pk.INSET_RANGE[1]


def test_the_old_grid_parameter_still_counts_as_a_stored_setting():
    assert pk.stored_settings(FakeFont("50")) == {"grid": 50.0}
    # And the settings parameter wins where both name it.
    assert pk.stored_settings(FakeFont("50", settings="grid: 20")) == {"grid": 20.0}


# --- The vertical span ----------------------------------------------------


def fake_layer(low, high):
    """Just enough of a GSLayer for `layer_span` to read its box."""
    return SimpleNamespace(
        bounds=SimpleNamespace(
            origin=SimpleNamespace(x=0.0, y=float(low)),
            size=SimpleNamespace(width=500.0, height=float(high - low)),
        )
    )


MASTER = SimpleNamespace(descender=-250.0, ascender=750.0)


def test_a_bubble_covers_its_glyph_and_no_more():
    """`resetBubble` and the tool's own default bubble both span the layer
    bounds, so a generated one that ran to the ascender on every glyph would
    disagree with every bubble drawn by hand."""
    assert pk.layer_span(fake_layer(-12, 512), MASTER) == (-12.0, 512.0)


def test_a_layer_with_no_ink_falls_back_to_the_master():
    assert pk.layer_span(fake_layer(0, 0), MASTER) == (-250.0, 750.0)


def test_the_wall_ends_exactly_on_the_box():
    """Scanlines sit at (row + 0.5) * step and land where they land; the ends
    are pinned so the bubble never overhangs its own box by half a step."""
    wall = pk.bubble_wall(flat(range(0, 10), 30.0), 10, 0.0, -12, 97, 500)
    assert wall[0][1] == -12 and wall[-1][1] == 97
    assert all(-12 <= y <= 97 for _, y in wall)


def test_a_glyph_shorter_than_one_scanline_still_gets_a_wall():
    wall = pk.bubble_wall({0: 30.0}, 10, 0.0, 2, 6, 500)
    assert len(wall) >= 2
    assert wall[0][1] == 2 and wall[-1][1] == 6


# --- Ported from AZ-Fingerprints, to catch a port that drifted ------------
def test_the_bevel_stops_a_profile_receding_faster_than_the_slope():
    """A one-row notch cannot be infinitely deep to a neighbour: the cone
    limits how fast the frontier may recede."""
    profile = {0: 0.0, 1: 200.0, 2: 0.0}
    beveled = pk.bevel_profile(profile, 10, slope=1.76)
    assert beveled[1] == pytest.approx(17.6)  # 1.76 * 10 units, one row away
    assert beveled[0] == 0.0 and beveled[2] == 0.0


def test_the_bevel_leaves_a_shallow_profile_alone():
    profile = {0: 0.0, 1: 5.0, 2: 0.0}
    assert pk.bevel_profile(profile, 10, slope=1.76) == profile


def test_the_cone_is_the_lowest_of_every_row_not_just_the_nearest():
    """A shallow row further away can be what a neighbour meets first, so the
    frontier is the envelope of cones from all of them."""
    profile = {0: 5.0, 1: 400.0}          # row 1 is deeply recessed
    limits = pk.cone_limits(profile, 10, slope=1.0)
    # From row 1 alone the frontier at row 2 would be 410; row 0 is nearer the
    # edge even two rows away.
    assert pk.cone_depth(limits, 2, 10, slope=1.0) == pytest.approx(25.0)


def test_a_row_that_runs_through_the_cone_still_counts():
    """`p` against `n`: the stem carries straight down at the same depth, into
    space `n` leaves open, and a descending neighbour meets it there."""
    n = flat(range(0, 50), 30)
    p = dict(flat(range(0, 50), 30))
    p.update(flat(range(-20, 0), 30))  # the stem, as close in as above
    assert pk.kern_fit(p, n, 10) > 20.0


def test_glyphs_within_tolerance_cluster_and_convention_names_the_group():
    profiles = {
        "n": flat(range(10), 30),
        "m": flat(range(10), 34),
        "u": flat(range(10), 38),
        "T": flat(range(10), 200),
    }
    groups = pk.cluster_kern_side(profiles, 20, 10)
    # `m` is the middle one and `m` is the alphabetical leader; the group is
    # called neither, because every member is within tolerance of every other
    # and `n` is the name a designer reads.
    assert set(groups) == {"n"}
    assert sorted(groups["n"]) == ["m", "n", "u"]
    assert "T" not in sum(groups.values(), [])


def test_the_medoid_pass_takes_back_what_the_greedy_pass_misplaced():
    """`b_join` lands on `a_lead` because that is the only group there is when
    its turn comes. The cluster it belongs to is built afterwards, and only a
    second look at the medoids can move it there.
    """
    profiles = {
        "a_lead": flat(range(10), 0),
        "b_join": flat(range(10), 20),
        "c_mid": flat(range(10), 30),
        "d_mid": flat(range(10), 34),
        "e_mid": flat(range(10), 38),
    }
    greedy = pk.cluster_kern_side(profiles, 20, 10, rounds=0)
    settled = pk.cluster_kern_side(profiles, 20, 10, rounds=2)
    assert sorted(next(m for m in greedy.values() if "b_join" in m)) == [
        "a_lead", "b_join",
    ]
    assert sorted(next(m for m in settled.values() if "b_join" in m)) == [
        "b_join", "c_mid", "d_mid", "e_mid",
    ]
    assert "a_lead" not in sum(settled.values(), [])


def test_the_inset_cap_is_a_percentage_of_the_advance():
    """A narrow glyph has less room to give away than a wide one, so a cap in
    units cannot be right for both. The settings hand on the percentage and
    the width decides what it is worth.
    """
    assert pk.auto_settings(SimpleNamespace(upm=1000), None,
                            prefs={pk.PREF_MAX_INSET: "22"})["max_inset"] == 22.0
    # unset, and outside the range the slider offers
    assert pk.auto_settings(SimpleNamespace(upm=1000), None,
                            prefs={})["max_inset"] == pk.MAX_INSET_PERCENT
    assert pk.auto_settings(SimpleNamespace(upm=1000), None,
                            prefs={pk.PREF_MAX_INSET: "999"})["max_inset"] == pk.INSET_RANGE[1]

    # ink far from both edges, so nothing but the cap decides where the wall sits
    profile = flat(range(0, 20), 400.0)
    for width, deepest in ((500, 50.0), (1000, 100.0)):
        nodes = pk.nodes_from_profile(profile, pk.LEFT, 10, 0.0, 0.0, 195.0, width,
                                      tolerance=0, max_inset=10.0)
        assert max(x for x, _ in nodes) == pytest.approx(deepest)


# --- Fitting the settings to hand kerning ---------------------------------


def test_two_walls_ask_for_the_whitespace_between_them():
    right = [(-20, 0), (-20, 100)]   # stored relative to the advance
    left = [(30, 0), (30, 100)]
    assert pk.kern_from_walls(right, left) == pytest.approx(-50.0)
    # and the closest approach decides it, not the average
    stepped = [(-20, 0), (-20, 50), (-5, 50), (-5, 100)]
    assert pk.kern_from_walls(stepped, left) == pytest.approx(-35.0)


def test_walls_that_never_meet_decide_nothing():
    assert pk.kern_from_walls([(-20, 0), (-20, 10)], [(30, 500), (30, 600)]) is None
    assert pk.kern_from_walls([], [(30, 0), (30, 10)]) is None


def test_the_fit_finds_the_settings_a_pair_was_kerned_with():
    """Kern a pair with a known combination, hand the fitter that value, and
    it should land on settings that reproduce it.

    The two glyphs recede in OPPOSITE directions, so their walls are closest
    somewhere in the middle rather than touching at one end - a pair whose
    extremes meet kerns 0 whatever the settings, and would prove nothing.
    """
    profiles = {
        "wedge": {
            pk.LEFT: flat(range(0, 20), 40.0),
            pk.RIGHT: {row: 40.0 + row * 12.0 for row in range(0, 20)},
        },
        "post": {
            pk.LEFT: {row: 40.0 + (19 - row) * 12.0 for row in range(0, 20)},
            pk.RIGHT: flat(range(0, 20), 40.0),
        },
    }
    geometry = {name: (0.0, 195.0, 500.0) for name in profiles}
    # every one of these is a value the full search visits, or it could not
    # possibly reproduce what they generate
    known = dict(angles=(40.0,), insets=(15.0,), amplitudes=(100.0,), spaces=(0.0,))
    assert known["angles"][0] in pk.FIT_ANGLES
    assert known["insets"][0] in pk.FIT_INSETS
    assert known["amplitudes"][0] in pk.FIT_AMPLITUDES
    assert known["spaces"][0] in pk.FIT_PERCENTS
    probe = pk.fit_settings(profiles, geometry, [("wedge", "post", 0.0)],
                            10, tolerance=5, **known)
    wanted = probe["misses"][0][3]
    assert wanted < -50  # the pair really does need kerning, or this proves nothing

    fitted = pk.fit_settings(profiles, geometry, [("wedge", "post", wanted)],
                             10, tolerance=5, spaces=(0.0,))
    assert fitted["pairs"] == 1
    assert fitted["error"] < 1.0  # the combination that made it is in the search
    assert fitted["space"] == 0.0  # and it does not reach for min space to get there
    assert fitted["unreachable"] == 0


def test_a_kern_the_model_cannot_reach_is_counted():
    profiles = {name: {pk.LEFT: flat(range(0, 20), 40.0), pk.RIGHT: flat(range(0, 20), 40.0)}
                for name in ("a", "b")}
    geometry = {name: (0.0, 195.0, 500.0) for name in profiles}
    # A wall never leaves its advance, so a pair asking to OPEN is unreachable.
    fitted = pk.fit_settings(profiles, geometry, [("a", "b", 40.0)], 10, tolerance=5)
    assert fitted["unreachable"] == 1


def test_fit_moves_only_the_pairs_that_already_kern():
    """A pair whose walls touch is at the spacing the file gave it, and Fit is
    not an instruction to change that. Nor does it ever make a positive kern.
    """
    assert pk.with_fit(-100.0, 20.0) == -80.0    # looser
    assert pk.with_fit(-100.0, -20.0) == -120.0  # tighter
    assert pk.with_fit(-10.0, 20.0) == 0.0       # as far as loose goes
    assert pk.with_fit(0.0, 20.0) == 0.0         # a flat pair stays flat
    assert pk.with_fit(0.0, -20.0) == 0.0        # in both directions
    assert pk.with_fit(-50.0, 0.0) == -50.0      # and 0 changes nothing


# --- Pulling the handover taut ---------------------------------------------
# THE NUMBERS ARE THE FONT'S OWN, read out of the Medium master of AZ Grotesk.
# O_WALL hands over to a circumflex sitting clear above it; o_WALL does the
# same, but its accent's foot reaches further out than the o's head does.

O_WALL = [(117.0, -16.0), (117.0, 38.0), (21.0, 198.0), (0.0, 348.0),
          (20.0, 498.0), (117.0, 662.0), (117.0, 716.0)]
O_ACCENT = [(190.0, 762.0), (243.0, 892.0)]
o_WALL = [(114.0, -16.0), (30.0, 98.0), (8.0, 168.0), (0.0, 252.0),
          (7.0, 338.0), (29.0, 408.0), (115.0, 524.0)]
o_ACCENT = [(81.0, 571.0), (195.0, 700.0)]
o_WALL_R = [(486.0, -16.0), (570.0, 98.0), (592.0, 168.0), (600.0, 252.0),
            (593.0, 338.0), (571.0, 408.0), (485.0, 524.0)]
o_ACCENT_R = [(528.0, 572.0), (445.0, 700.0)]


def taut(base, accent, keep_min=True):
    merged = pk.union_walls([base, accent], keep_min=keep_min)
    return pk.taut_join(merged, [base, accent], keep_min=keep_min)


def test_the_step_at_the_handover_is_pulled_out():
    """`Ocircumflex`: the O's wall stops at 117 and the circumflex's starts at
    190, so the join runs almost flat across 46 units of height before turning
    up again. Pulled taut it is one straight run from the O's head to the top
    of the accent."""
    assert taut(O_WALL, O_ACCENT) == O_WALL + [(243.0, 892.0)]


def test_an_accent_reaching_further_out_is_left_standing():
    """`ocircumflex`: the accent's foot at 81 is further out than the o's head
    at 115. The string is pulled round the OUTSIDE, so it rests on that foot -
    cutting it away would put the wall 55 units inside the accent's own
    whitespace."""
    assert taut(o_WALL, o_ACCENT) == o_WALL + o_ACCENT


def test_the_right_side_measures_out_the_other_way():
    """Out is the larger x on a right wall. The accent's foot at 528 reaches
    past the o's head at 485 and stays..."""
    assert taut(o_WALL_R, o_ACCENT_R, keep_min=False) == o_WALL_R + o_ACCENT_R
    # ...while a step that cuts back IN goes, exactly as on the left.
    inward = [(430.0, 572.0), (520.0, 700.0)]
    assert taut(o_WALL_R, inward, keep_min=False) == o_WALL_R + [(520.0, 700.0)]


def test_the_wall_never_moves_into_the_ink():
    """The one property that matters: pulling taut may give whitespace away,
    never take ink. Every row of the taut wall is at or outside the row the
    union gave, on both sides."""
    for base, accent, keep_min in ((O_WALL, O_ACCENT, True),
                                   (o_WALL, o_ACCENT, True),
                                   (o_WALL_R, o_ACCENT_R, False)):
        merged = pk.union_walls([base, accent], keep_min=keep_min)
        pulled = pk.taut_join(merged, [base, accent], keep_min=keep_min)
        for x, y in merged:
            got = pk.xs_at(pulled, y)
            assert got, f'row {y} disappeared'
            if keep_min:
                assert min(got) <= x + 1e-6
            else:
                assert max(got) >= x - 1e-6


def test_pieces_sharing_a_height_are_not_a_handover():
    """Two components side by side over the same rows. There is no air
    between them to pull a string across, so the row-by-row union stands."""
    base = [(50.0, 0.0), (50.0, 500.0)]
    accent = [(20.0, 400.0), (80.0, 600.0)]
    merged = pk.union_walls([base, accent], keep_min=True)
    assert pk.taut_join(merged, [base, accent], keep_min=True) == merged


def test_one_piece_is_never_pulled_taut():
    wall = [(50.0, 0.0), (10.0, 300.0), (50.0, 600.0)]
    assert pk.taut_join(wall, [wall], keep_min=True) == wall


# --- A run over the selection only ------------------------------------------
# `names` narrows the whole run, not just what gets written: a glyph outside it
# is never measured, so it is not in anybody's cluster either. What is pinned
# here is that the filter reaches the scan at all - it is the scan that costs
# the minutes, and a filter applied any later would save none of them.


class _Layer:
    def __init__(self, name, width=500):
        self.width = width
        self.parent = SimpleNamespace(name=name)


class _Glyph:
    def __init__(self, name):
        self.name = name
        self.layers = {"m1": _Layer(name)}


class _NamedFont:
    upm = 1000

    def __init__(self, *names):
        self.glyphs = [_Glyph(name) for name in names]


def _stubMeasuring(monkeypatch):
    """Everything collect_sides leans on, canned. -> the list it scanned."""
    scanned = []
    monkeypatch.setattr(pk, "measurable", lambda glyph, layer: True)

    def scan(layer, step, skip_marks=True):
        scanned.append(layer.parent.name)
        return ([0.0] * pk.MIN_ROWS_TO_MEASURE,)

    monkeypatch.setattr(pk, "scan_layer", scan)
    monkeypatch.setattr(pk, "kern_profiles",
                        lambda rows, width, step: {pk.LEFT: (1.0,), pk.RIGHT: (2.0,)})
    monkeypatch.setattr(pk, "layer_span", lambda layer, master: (0.0, 700.0))
    return scanned


def test_collect_sides_measures_every_glyph_when_told_nothing(monkeypatch):
    scanned = _stubMeasuring(monkeypatch)
    font = _NamedFont("a", "b", "c")
    sides, geometry = pk.collect_sides(font, SimpleNamespace(id="m1"), 10)
    assert scanned == ["a", "b", "c"]
    assert sorted(geometry) == ["a", "b", "c"]


def test_collect_sides_does_not_even_look_at_the_rest(monkeypatch):
    """Not measured and then dropped - not measured."""
    scanned = _stubMeasuring(monkeypatch)
    font = _NamedFont("a", "b", "c")
    sides, geometry = pk.collect_sides(font, SimpleNamespace(id="m1"), 10,
                                       names={"a", "c"})
    assert scanned == ["a", "c"], scanned
    assert sorted(geometry) == ["a", "c"]
    assert sorted(sides[pk.LEFT]) == ["a", "c"]


def test_the_plan_hands_the_names_down_to_the_scan(monkeypatch):
    """The filter is no use to anybody if the plan keeps it to itself."""
    seen = {}

    def collect(font, master, step, progress=None, names=None):
        seen["names"] = names
        return {pk.LEFT: {}, pk.RIGHT: {}}, {}

    monkeypatch.setattr(pk, "collect_sides", collect)
    font = SimpleNamespace(upm=1000, glyphs=[])
    pk.auto_bubble_plan(font, SimpleNamespace(id="m1"), step=10, tolerance=5,
                        names={"a"})
    assert seen["names"] == {"a"}


def test_no_names_still_means_the_whole_font(monkeypatch):
    seen = {}

    def collect(font, master, step, progress=None, names=None):
        seen["names"] = names
        return {pk.LEFT: {}, pk.RIGHT: {}}, {}

    monkeypatch.setattr(pk, "collect_sides", collect)
    font = SimpleNamespace(upm=1000, glyphs=[])
    pk.auto_bubble_plan(font, SimpleNamespace(id="m1"), step=10, tolerance=5)
    assert seen["names"] is None


# --- Grouping on the font's own kerning groups -------------------------------
# A font that has been kerned already holds an answer to "which glyphs share a
# side" - one somebody decided on and has been kerning against. Measuring the
# shapes afresh proposes a second, different set of groups for the same font,
# which is why this road exists beside the shape one.


class _GroupedGlyph:
    def __init__(self, name, left=None, right=None):
        self.name = name
        if left is not None:
            self.leftKerningGroup = left
        if right is not None:
            self.rightKerningGroup = right


class _GroupedFont:
    upm = 1000

    def __init__(self, *glyphs):
        self.glyphs = list(glyphs)


def test_the_left_side_reads_the_left_group():
    """The spelling a kerning table uses says the opposite - a glyph's LEFT
    group is written `@MMK_R_` - which is an invitation to swap these two."""
    glyph = _GroupedGlyph("aacute", left="a", right="o")
    assert pk.kerning_side_group(glyph, pk.LEFT) == "a"
    assert pk.kerning_side_group(glyph, pk.RIGHT) == "o"


def test_no_group_is_one_answer_and_not_three():
    """A missing attribute, a None and a blank field all mean the same."""
    assert pk.kerning_side_group(_GroupedGlyph("a"), pk.LEFT) == ""
    assert pk.kerning_side_group(_GroupedGlyph("a", left=None), pk.LEFT) == ""
    assert pk.kerning_side_group(_GroupedGlyph("a", left=""), pk.LEFT) == ""


def test_the_members_of_each_group():
    font = _GroupedFont(
        _GroupedGlyph("n", left="n"),
        _GroupedGlyph("m", left="n"),
        _GroupedGlyph("h", left="n"),
        _GroupedGlyph("o", left="o"),
        _GroupedGlyph("c", left="o"),
    )
    assert pk.kerning_group_members(font, pk.LEFT) == {
        "n": ["h", "m", "n"], "o": ["c", "o"]}


def test_a_group_of_one_is_not_a_group():
    """Nobody borrows from it, and a band of one cell says nothing."""
    font = _GroupedFont(
        _GroupedGlyph("n", left="n"),
        _GroupedGlyph("o", left="o"),
        _GroupedGlyph("c", left="o"),
    )
    assert list(pk.kerning_group_members(font, pk.LEFT)) == ["o"]


def test_a_run_over_a_selection_groups_the_selection():
    """Not a reference pointing at a glyph the run never measured."""
    font = _GroupedFont(
        _GroupedGlyph("n", left="n"),
        _GroupedGlyph("m", left="n"),
        _GroupedGlyph("h", left="n"),
    )
    assert pk.kerning_group_members(font, pk.LEFT, names={"n", "m"}) == {
        "n": ["m", "n"]}
    # And down to one member, the group goes with it.
    assert pk.kerning_group_members(font, pk.LEFT, names={"n"}) == {}


def test_the_glyph_the_group_is_named_after_carries_the_wall(monkeypatch):
    """A designer who wrote `n` in twelve group fields has already said which
    glyph is the model."""
    def refuse(*a, **k):
        raise AssertionError("overruled the designer")
    monkeypatch.setattr(pk, "kern_group_name", refuse)
    assert pk.kerning_group_anchor("n", ["h", "m", "n"], {}, 10) == "n"


def test_a_group_named_after_no_glyph_falls_back_to_the_shape_road(monkeypatch):
    """`stem`, or a group whose `n` had no ink to scan."""
    seen = {}

    def chosen(members, profiles, step, limits=None):
        seen["members"] = members
        return "m"

    monkeypatch.setattr(pk, "kern_group_name", chosen)
    assert pk.kerning_group_anchor("stem", ["h", "m"], {}, 10) == "m"
    assert seen["members"] == ["h", "m"]


def test_only_glyphs_that_were_measured_get_into_a_cluster():
    """A glyph with no ink has no wall to lend or to borrow, whatever its
    kerning group says about it."""
    font = _GroupedFont(
        _GroupedGlyph("n", left="n"),
        _GroupedGlyph("m", left="n"),
        _GroupedGlyph("space", left="n"),
    )
    clusters = pk.kerning_group_clusters(font, {"n": {0: 1.0}, "m": {0: 1.0}},
                                         pk.LEFT, 10)
    assert clusters == {"n": ["m", "n"]}


def test_how_many_groups_a_run_would_have_to_work_from():
    font = _GroupedFont(
        _GroupedGlyph("n", left="n", right="n"),
        _GroupedGlyph("m", left="n", right="n"),
        _GroupedGlyph("o", left="o"),
        _GroupedGlyph("c", left="o"),
    )
    assert pk.kerning_groups_present(font, (pk.LEFT,)) == 2
    assert pk.kerning_groups_present(font, (pk.RIGHT,)) == 1
    assert pk.kerning_groups_present(font, (pk.LEFT, pk.RIGHT)) == 3
    assert pk.kerning_groups_present(_GroupedFont(_GroupedGlyph("n"))) == 0


def _stubPlanScan(monkeypatch, profiles):
    """A plan run with the measuring canned. -> nothing"""
    monkeypatch.setattr(pk, "collect_sides", lambda font, master, step,
                        progress=None, names=None: (
        {pk.LEFT: dict(profiles), pk.RIGHT: dict(profiles)},
        {name: (0.0, 700.0, 500.0) for name in profiles}))
    monkeypatch.setattr(pk, "nodes_from_profile", lambda *a, **k: [(0, 0)])


def test_the_kerning_road_never_asks_the_shape_one(monkeypatch):
    """Two roads to a group, and taking one means not taking the other."""
    _stubPlanScan(monkeypatch, {"n": {0: 1.0}, "m": {0: 1.0}})

    def refuse(*a, **k):
        raise AssertionError("measured the shapes anyway")

    monkeypatch.setattr(pk, "cluster_kern_side", refuse)
    font = _GroupedFont(_GroupedGlyph("n", left="n", right="n"),
                        _GroupedGlyph("m", left="n", right="n"))
    plan = pk.auto_bubble_plan(font, SimpleNamespace(id="m1"), step=10,
                               tolerance=5, gap=20,
                               source=pk.BY_KERNING_GROUPS)
    assert plan[pk.LEFT]["refer"] == {"m": "n"}
    # The representative is the one carrying a drawing; the member is not.
    assert sorted(plan[pk.LEFT]["nodes"]) == ["n"]


def test_the_shape_road_is_still_the_default(monkeypatch):
    _stubPlanScan(monkeypatch, {"n": {0: 1.0}, "m": {0: 1.0}})
    asked = []
    monkeypatch.setattr(pk, "cluster_kern_side",
                        lambda *a, **k: asked.append(1) or {})

    def refuse(*a, **k):
        raise AssertionError("read the kerning groups without being asked")

    monkeypatch.setattr(pk, "kerning_group_clusters", refuse)
    font = _GroupedFont(_GroupedGlyph("n", left="n"), _GroupedGlyph("m", left="n"))
    pk.auto_bubble_plan(font, SimpleNamespace(id="m1"), step=10, tolerance=5,
                        gap=20)
    assert asked == [1, 1], "one clustering a side"
