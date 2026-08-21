# encoding: utf-8
"""The two text fields the info box and the settings window are typed into.

`NudgeEditText` steps a number with the arrow keys, ten at a time with shift.
`CompletingEditText` offers the font's own glyph names while a reference is
typed - the field takes a glyph NAME, which past the alphabet is not something
anybody holds in their head.

Both are vanilla subclasses carrying a delegate, and both fall back to a plain
`EditText` on a vanilla that keeps its delegate somewhere else: no nudging and
no completion, but a window.
"""

import traceback

import vanilla
from GlyphsApp import Glyphs

from BKCommonLogic import log


# Arrow keys step a numeric field, shift-arrow by ten. The field editor
# turns the key into one of these selectors before anything else sees it,
# and shift picks a different selector rather than a modifier flag.
# How many glyph names a reference field offers at once. Enough to find the
# one you meant, few enough that the list is read rather than scrolled.
GLYPH_COMPLETIONS = 20
# What the completion popup starts with selected: nothing. A real index would
# be typed into the field straight away, which is autocorrect, not a list.
NOTHING_PICKED = -1

NUDGE_STEPS = {
	'moveUp:': 1,
	'moveDown:': -1,
	'moveUpAndModifySelection:': 10,
	'moveDownAndModifySelection:': -10,
}

try:
	from vanilla.vanillaEditText import VanillaEditTextDelegate

	class BubbleKernNudgeDelegate(VanillaEditTextDelegate):

		def control_textView_doCommandBySelector_(self, control, textView, selector):
			try:
				name = selector.decode() if isinstance(selector, bytes) else str(selector)
				step = NUDGE_STEPS.get(name)
				if step is None:
					return False
				try:
					value = int(round(float(str(textView.string()).strip())))
				except ValueError:
					value = 0  # blank is 'auto': the first press starts from nothing
				value = max(0, value + step)  # none of these fields means anything negative
				textView.setString_(str(value))
				control.setStringValue_(str(value))
				self.action_(control)  # save the preference and redraw the preview
				return True
			except Exception:
				log(f'nudge error: {traceback.format_exc()}', error=True)
				return False

	class NudgeEditText(vanilla.EditText):
		nsTextFieldDelegateClass = BubbleKernNudgeDelegate

	class BubbleKernCompletionDelegate(VanillaEditTextDelegate):
		"""Offer the font's own glyph names while a reference is typed.

		The field takes a glyph NAME, which for anything past the alphabet is
		something nobody holds in their head - `germandbls`, `quotedblleft`,
		`uni0237`. The font already knows all of them.
		"""

		def control_textView_completions_forPartialWordRange_indexOfSelectedItem_(
				self, control, textView, words, charRange, index):
			# TAKES THE INDEX AND RETURNS IT. The last argument is an
			# `NSInteger *` that PyObjC reads as INOUT, so this hands back
			# `(names, index)` - a bare list raises `Need tuple of 2 arguments
			# as result` from inside the bridge, AFTER this method has already
			# returned, where no `except` here can see it. The list then never
			# appears and nothing is logged. NOTHING_PICKED so the popup only
			# offers: a selected row would type itself into the field and take
			# the next keystroke's meaning away.
			try:
				typed = str(textView.string())[
					charRange.location:charRange.location + charRange.length]
				font = Glyphs.font
				if not typed or font is None:
					return ([], NOTHING_PICKED)
				lowered = typed.lower()
				names = [glyph.name for glyph in font.glyphs
					if glyph.name and glyph.name.lower().startswith(lowered)]
				# WHAT WAS TYPED, AS TYPED, FIRST - then shortest, so `a` offers `a`
				# before `aacute` and never buries the letter under its accents.
				names.sort(key=lambda name: (not name.startswith(typed),
						len(name), name))
				return (names[:GLYPH_COMPLETIONS], NOTHING_PICKED)
			except Exception:
				log(f'completion error: {traceback.format_exc()}', error=True)
				return ([], NOTHING_PICKED)

		def controlTextDidChange_(self, notification):
			# ASKED FOR ON EVERY KEYSTROKE. An NSTextField never completes by
			# itself - `complete:` is what puts the list up - and the guard is
			# because completing changes the text, which arrives back here.
			try:
				if not getattr(self, '_completing', False):
					self._completing = True
					try:
						editor = notification.object().currentEditor()
						if editor is not None:
							editor.complete_(None)
					finally:
						self._completing = False
			except Exception:
				log(f'completion error: {traceback.format_exc()}', error=True)
			VanillaEditTextDelegate.controlTextDidChange_(self, notification)

	class CompletingEditText(vanilla.EditText):
		nsTextFieldDelegateClass = BubbleKernCompletionDelegate

except Exception:  # a vanilla that keeps its delegate elsewhere: no nudging, but a window
	NudgeEditText = vanilla.EditText
	CompletingEditText = vanilla.EditText
