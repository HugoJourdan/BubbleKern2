# MenuTitle: Rename BubbleKern data to PolyKern
# -*- coding: utf-8 -*-
__doc__ = """
Carries the walls a font had under BubbleKern over to the keys PolyKern reads.

PolyKern writes `PolyKernNodesL` where BubbleKern wrote `BubbleKernNodesL`, and
reads nothing under the old name - so a file drawn with the old plugin opens
with its bubbles intact in the file but invisible to the new one. This renames
them in place.

MATCHED ON THE NAME, NOT ON A LIST OF KEYS. There are twelve wall keys, two
custom parameters and a couple of font-level flags, and `usePolyKern` is in no
constant anywhere - a list would have missed it. Anything holding the old name
comes across.

MOVED, NOT COPIED: a key left behind under both names doubles what the file
carries and makes a second run ambiguous. Set REVERSE to go back.

Run it on a file you have not saved over yet, or on a copy. It is one undo step
per glyph, so a mistake is undoable, but a backup costs nothing.
"""

LEGACY, CURRENT = 'BubbleKern', 'PolyKern'

# --- Knobs ------------------------------------------------------------------

REVERSE = False  # True renames PolyKern keys back to BubbleKern
ALL_OPEN_FONTS = False  # True does every open font rather than the front one


# --- The rename -------------------------------------------------------------


def renameUserData(holder, old, new):
	"""Rename every key of `holder`'s userData holding `old`. -> (moved, kept)

	`kept` counts a key that could not move because the new name was already
	taken - a layer that has been through both plugins. The value already under
	the new name is the one PolyKern reads, so it is the one that stays.
	"""
	try:
		userData = holder.userData
		keys = list(userData.keys()) if userData is not None else []
	except Exception:
		return 0, 0
	moved = kept = 0
	for key in keys:
		if not isinstance(key, str) or old not in key:
			continue
		renamed = key.replace(old, new)
		if renamed == key:
			continue
		if userData[renamed] is not None:
			kept += 1
			continue
		userData[renamed] = userData[key]
		del userData[key]
		moved += 1
	return moved, kept


def renameParameters(holder, old, new):
	"""The same for a font's or a master's custom parameters. -> (moved, kept)"""
	try:
		names = [parameter.name for parameter in holder.customParameters]
	except Exception:
		return 0, 0
	moved = kept = 0
	for name in names:
		if not isinstance(name, str) or old not in name:
			continue
		renamed = name.replace(old, new)
		if renamed == name:
			continue
		try:
			if holder.customParameters[renamed] is not None:
				kept += 1
				continue
			holder.customParameters[renamed] = holder.customParameters[name]
			del holder.customParameters[name]
			moved += 1
		except Exception:
			continue
	return moved, kept


def renameFont(font, reverse=False):
	"""Every key in one font. -> (moved, kept, glyphs touched)

	ONE UNDO STEP PER GLYPH, which is how the plugin itself writes a wall: a
	single step over a whole font would be a step nobody dares take back.
	"""
	old, new = (CURRENT, LEGACY) if reverse else (LEGACY, CURRENT)
	moved, kept = renameUserData(font, old, new)
	for holder in [font] + list(font.masters):
		one, two = renameParameters(holder, old, new)
		moved, kept = moved + one, kept + two
	for holder in font.masters:
		one, two = renameUserData(holder, old, new)
		moved, kept = moved + one, kept + two
	touched = 0
	for glyph in font.glyphs:
		glyph.beginUndo()
		try:
			one, two = renameUserData(glyph, old, new)
			for layer in glyph.layers:
				three, four = renameUserData(layer, old, new)
				one, two = one + three, two + four
		finally:
			glyph.endUndo()
		moved, kept = moved + one, kept + two
		if one:
			touched += 1
	return moved, kept, touched


# --- Running it -------------------------------------------------------------


def report(results, reverse=False):
	"""What to put in front of the person who ran this. -> str"""
	old, new = (CURRENT, LEGACY) if reverse else (LEGACY, CURRENT)
	if not results:
		return 'No font is open.'
	lines = []
	for name, (moved, kept, touched) in results:
		if not moved and not kept:
			lines.append(f'{name}: nothing under {old}.')
			continue
		line = f'{name}: {moved} keys renamed to {new}, {touched} glyphs.'
		if kept:
			line += f' {kept} left alone - already had a {new} key.'
		lines.append(line)
	return '\n'.join(lines)


def main():
	from GlyphsApp import Glyphs, Message
	fonts = list(Glyphs.fonts) if ALL_OPEN_FONTS else (
			[Glyphs.font] if Glyphs.font is not None else [])
	results = []
	for font in fonts:
		font.disableUpdateInterface()
		try:
			results.append((font.familyName, renameFont(font, REVERSE)))
		finally:
			font.enableUpdateInterface()
	# BY KEYWORD: `Message` has been declared both ways round across Glyphs
	# versions, and this reads the same under either.
	Message(title='PolyKern', message=report(results, REVERSE), OKButton=None)


def _fontIsOpen():
	try:
		from GlyphsApp import Glyphs
	except ImportError:
		return False
	return getattr(Glyphs, 'font', None) is not None


# RUN WHEN GLYPHS RUNS THIS FILE, NOT WHEN THE TESTS IMPORT IT. Glyphs executes
# a script top to bottom and there is nothing to hook; what tells the two apart
# is that the tests import it under a name of their own, with no font open.
if __name__ == '__main__' or _fontIsOpen():
	main()
