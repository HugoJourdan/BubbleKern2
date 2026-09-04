# encoding: utf-8
"""Which glyphs the one being edited most wants to be seen beside.

A WALL IS ONLY EVER RIGHT ABOUT A PAIR. Nothing about `A`'s right side can be
judged with `A` on its own, and the pairs worth judging it against are not the
ones that come to mind - they are the ones that turn up in text, which is a
different list and a longer one than anybody keeps in their head.

THE LIST IS ALREADY IN THE PLUGIN. `PKAutoBubble.relevant_pairs` is André
Fuchs's kerning pairs, counted over a large multi-language corpus and ranked,
and the kerner already uses it to decide which pairs are worth writing. The
same ranking answers "what should I be looking at while I draw this?".

NO IMPORTS FROM GLYPHS. Everything here takes what it needs as an argument -
the character-to-name table, a glyph's userData - so the choosing can be tested
without a font, and the drawing is somebody else's job.
"""

import PKAutoBubble as auto


# HOW MANY PARTNERS A SIDE GETS. Six each way is twelve pairs, which is what
# fits a preview panel at a size worth looking at; the ranking means the ones
# left out are the ones that matter least.
PARTNER_LIMIT = 6

# glyph.userData: THE PARTNERS SOMEBODY CHOSE FOR THIS GLYPH, INSTEAD OF THE
# ONES THE LIST PICKS. Per glyph, not per layer: which letters `A` wants to be
# seen beside is a fact about the alphabet, not about the master.
PAIRS_KEY = 'PolyKernPairs'

# A PAIR AGAINST THE WORD SPACE DRAWS NOTHING. The list has plenty of them -
# they are among the commonest pairs in any text - and every one of them would
# be a gap in the row with nothing to judge in it.
SPACES = '  '


def baseName(name):
	"""The glyph a suffixed one is a variant of. -> str

	`A.ss01` is an `A` as far as the pair list is concerned: the list is
	written in characters, an alternate has none of its own, and the pairs its
	base turns up in are the pairs it is drawn to stand in.

	A name that OPENS with a dot, like `.notdef`, is its own base - that dot is
	part of the name rather than a suffix on nothing.
	"""
	if not name or name.startswith('.'):
		return name or ''
	return name.split('.', 1)[0] or name


def charactersFor(name, namesByCharacter):
	"""Which characters this glyph draws. -> set

	Falls back to the base glyph's, so an alternate is asked about as what it
	is an alternate OF.
	"""
	found = {character for character, drawn in namesByCharacter.items()
		if drawn == name}
	if found:
		return found
	base = baseName(name)
	if base == name:
		return set()
	return {character for character, drawn in namesByCharacter.items()
		if drawn == base}


def partners(name, namesByCharacter, limit=PARTNER_LIMIT):
	"""The glyphs this one stands beside most often. -> (before, after)

	`before` come BEFORE it in the pairs the list has and `after` after it, so
	the first exercises this glyph's LEFT wall and the second its right. Both
	are ranked as the list ranks them - by how often the pair turns up in
	running text - and cut to `limit`.
	"""
	characters = charactersFor(name, namesByCharacter)
	if not characters:
		return ([], [])
	before, after = [], []
	for pair in auto.relevant_pairs():
		left, right = pair[0], pair[1]
		if right in characters and left not in SPACES:
			partner = namesByCharacter.get(left)
			if partner is not None and partner not in before:
				before.append(partner)
		if left in characters and right not in SPACES:
			partner = namesByCharacter.get(right)
			if partner is not None and partner not in after:
				after.append(partner)
		if len(before) >= limit and len(after) >= limit:
			break
	return (before[:limit], after[:limit])


def chosenPartners(glyph, namesByCharacter=None):
	"""The partners somebody typed for this glyph. -> [names], or None

	None when nothing is stored, which is what tells a caller to go and ask the
	list. A stored list that turns out to be empty is an ANSWER - "show me
	nothing for this one" - and comes back as an empty list, not as None.

	WRITTEN IN WHATEVER IS QUICKEST TO TYPE: glyph names, or the characters
	themselves. `V T o` and `VTo` mean the same six pairs, which is why the
	table is wanted here: without it there is no telling `VTo` from a glyph of
	that name.
	"""
	if glyph is None:
		return None
	try:
		stored = glyph.userData[PAIRS_KEY]
	except Exception:
		return None
	if stored is None:
		return None
	if isinstance(stored, (list, tuple)):
		words = [str(word) for word in stored]
	else:
		words = str(stored).split()
	names = []
	for word in words:
		if not word:
			continue
		found = _resolve(word, namesByCharacter)
		for one in found:
			if one not in names:
				names.append(one)
	return names


def _resolve(word, namesByCharacter):
	"""One typed word as glyph names. -> [str]

	A NAME FIRST, then the word read a character at a time. `V` is both, and
	means the same thing either way; `Vo` is not a glyph anybody has, and
	reading it as two is what lets a list be typed without spaces.
	"""
	table = namesByCharacter or {}
	if table and word in table.values():
		return [word]
	if not table:
		return [word]  # nothing to read it with: take it as a name
	if all(character in table for character in word):
		return [table[character] for character in word]
	return [word]


def pairsFor(glyph, name, namesByCharacter, limit=PARTNER_LIMIT):
	"""Every pair to show for this glyph, in the order to show them. -> [(l, r)]

	THIS GLYPH'S LEFT SIDE FIRST, which is the order the info box asks about
	the two sides in: the pairs where it comes second exercise its left wall,
	the pairs where it comes first exercise its right.
	"""
	chosen = chosenPartners(glyph, namesByCharacter)
	if chosen is None:
		before, after = partners(name, namesByCharacter, limit)
	else:
		# ONE LIST FOR BOTH SIDES. Somebody naming the partners for `A` is
		# naming the letters `A` has to work beside, not the letters that may
		# stand to its left; asking for the two separately would be asking the
		# same question twice for the sake of the rare glyph that answers it
		# differently.
		before = after = chosen[:limit] if limit else list(chosen)
	return ([(partner, name) for partner in before]
		+ [(name, partner) for partner in after])


# --- Where the row of pairs goes --------------------------------------------

# WHAT THE ROW LEAVES AT THE ENDS, as a fraction of the panel's width, and how
# much of its height the line is allowed to take. A line filling the panel edge
# to edge reads as something that has overflowed; the air is what says it fits.
SIDE_PAD = 0.04
PANEL_FILL = 0.7
# THE GAP BETWEEN ONE PAIR AND THE NEXT, in ems. It has to be plainly wider
# than any kern, or the row reads as one long word and the pairs stop being
# pairs; a quarter of an em is about a word space in most texts, and reads as
# one.
PAIR_GAP_EM = 0.28


def placeRun(panel, total, ascender, descender, pad=SIDE_PAD, fill=PANEL_FILL):
	"""Fit a row of that many units into the panel. -> (scale, x, baseline)

	CENTRED, AND SCALED TO WHICHEVER RUNS OUT FIRST - the panel's width or its
	height. A row of two pairs and a row of twelve are both worth looking at,
	and neither is worth looking at cut off.

	None when there is nothing to place or nowhere to put it, which is a panel
	too small to draw in or a run of nothing.
	"""
	try:
		x, y, width, height = (float(value) for value in panel)
		total = float(total)
		lineHeight = float(ascender) - float(descender)
		if total <= 0 or width <= 0 or height <= 0 or lineHeight <= 0:
			return None
		room = width * (1.0 - 2.0 * pad)
		scale = min(room / total, height * fill / lineHeight)
		if scale <= 0:
			return None
		left = x + (width - total * scale) / 2.0
		baseline = y + (height - lineHeight * scale) / 2.0 - float(descender) * scale
		return (scale, left, baseline)
	except Exception:
		return None
