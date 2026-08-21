"""The Font Info editor for the `BubbleKern` parameter.

Glyphs lets a plugin own the UI for a custom parameter: register a window
controller with `GSCallbackHandler.addCustomParameterSheetController:forParameter:`
and clicking the value in Font Info opens it instead of a text field. This is
for the times when nobody wants to remember whether it is `turn` or `angle`.

A name and a field per setting, which is the parameter's own line laid out one
row to a setting. Glyphs hands over an ARRAY of parameters, because Font Info
edits every selected master at once, so only the fields actually TOUCHED here
are written and each parameter keeps whatever else it was carrying.
"""

from __future__ import division, print_function, unicode_literals


import traceback

import objc
import vanilla
from AppKit import (NSApp, NSFocusRingTypeNone, NSModalResponseOK,
	NSWindowController)

import BKAutoBubble as auto
from BKCommonLogic import log

PARAMETER_TITLE = 'BubbleKern settings'
# WHAT `setCustomParameters:error:` HANDS BACK. The SDK sample calls it a BOOL
# and returns YES; Glyphs reads it as three states, and YES is the one that
# means "handled, show nothing" - so the sheet never opened and the parameter
# could not be edited at all. 2 asks Glyphs to present the NSError; anything
# else, 0 here, is the one that goes on to `runDialog:modalForWindow:`.
SHOW_THE_DIALOG = 0
# Held open: Glyphs does not keep a reference to the controller it built, and a
# sheet that gets collected mid-edit takes the window with it.
_open = set()


class BubbleKernParameterSheet(NSWindowController):

	def init(self):
		try:
			self.parameters = []
			self.shown = {}
			self.blank = True
			rows = len(auto.SETTING_UI)
			height = 15 + rows * 28 + 55
			self.panel = vanilla.Window((195, height), PARAMETER_TITLE)
			panel = self.panel
			# FIELDS, NOT SLIDERS. A parameter is a line of numbers a person
			# reads and types; the settings panel is where a number gets found
			# by moving something and watching the drawing change.
			#
			# NARROW ONES: the widest thing any of them will hold is a three
			# figure depth, and a field sized for a sentence invites one.
			for index, (key, label, span, form) in enumerate(auto.SETTING_UI):
				top = 15 + index * 28
				setattr(panel, key + 'Label',
					vanilla.TextBox((15, top + 3, 105, 18), label))
				setattr(panel, key, vanilla.EditText((130, top, 50, 22), '',
					callback=self.valueEdited))
			panel.okButton = vanilla.Button((-95, height - 34, 80, 20), 'OK',
				callback=self.okDialog)
			panel.setDefaultButton(panel.okButton)
			# NO FOCUS RINGS. A field being edited says so with its caret; the
			# blue halo is a second answer to a question already answered, and
			# on six controls in a row it is the loudest thing in the window.
			for control in ([getattr(panel, key) for key, _, _, _ in auto.SETTING_UI]
					+ [panel.okButton]):
				view = (control.getNSTextField() if hasattr(control, 'getNSTextField')
					else control.getNSButton())
				view.setFocusRingType_(NSFocusRingTypeNone)
			self = objc.super(BubbleKernParameterSheet, self).initWithWindow_(
				panel.getNSWindow())
			return self
		except Exception:
			log(f'BubbleKern parameter sheet: {traceback.format_exc()}', error=True)
			return None

	# --- What Glyphs calls ------------------------------------------------

	def setCustomParameters_error_(self, parameters, error):
		try:
			self.parameters = list(parameters or [])
			first = auto.parse_settings(
				self.parameters[0].value if self.parameters else None)
			# An EMPTY parameter is someone saying "this file carries settings"
			# and not yet which, so everything shown counts as chosen.
			self.blank = not first
			panel = self.panel
			for key, label, span, form in auto.SETTING_UI:
				value = first.get(key)
				if value is None:
					value = auto.setting_value(key)  # what it falls through to
				getattr(panel, key).set(auto._tidy(value))
				self.shown[key] = str(getattr(panel, key).get()).strip()
			# THE GRID IS NOT HERE. A parameter carrying `grid:` keeps it -
			# nothing this sheet writes goes near a setting it does not show.
			self.blank = self.blank or not self.parameters
			return SHOW_THE_DIALOG
		except Exception:
			log(f'BubbleKern parameter sheet: {traceback.format_exc()}', error=True)
			return SHOW_THE_DIALOG

	setCustomParameters_error_ = objc.selector(
		setCustomParameters_error_, selector=b'setCustomParameters:error:',
		signature=objc._C_NSBOOL + b'@:@^@')

	def runDialog_modalForWindow_(self, sender, window):
		# GLYPHS PASSES NIL for the window it wants this attached to, so the
		# window to hang off is whichever one the click came from. Failing
		# that, stand on our own: a dialog nobody can open is worse than a
		# dialog in the wrong place, and with no editor registered at all the
		# parameter would still have its text field.
		try:
			_open.add(self)
			own = self.window()
			if own is None:
				log('BubbleKern parameter sheet: no window to show', error=True)
				return
			host = window or NSApp().keyWindow() or NSApp().mainWindow()
			if host is not None and host is not own:
				host.beginSheet_completionHandler_(own, None)
			else:
				own.center()
				self.showWindow_(sender)
				own.makeKeyAndOrderFront_(sender)
		except Exception:
			log(f'BubbleKern parameter sheet: {traceback.format_exc()}', error=True)

	# --- The controls -----------------------------------------------------

	@objc.python_method
	def texts(self):
		"""What the fields hold, as typed. -> {key: str}"""
		panel = self.panel
		return {key: str(getattr(panel, key).get()).strip()
				for key, label, span, form in auto.SETTING_UI}

	@objc.python_method
	def valueEdited(self, sender=None):
		pass

	@objc.python_method
	def okDialog(self, sender=None):
		try:
			# ONLY WHAT WAS TOUCHED. Font Info may be editing several masters,
			# and a field nobody typed in is not an instruction to make them
			# all agree about it. A field left EMPTY is not an answer either:
			# that setting keeps whatever the parameter already said.
			chosen = {}
			for key, text in self.texts().items():
				if text and (self.blank or text != self.shown.get(key)):
					chosen[key] = auto._number(text, 0.0)
			for parameter in self.parameters:
				settings = auto.parse_settings(parameter.value)
				settings.update(chosen)
				parameter.value = auto.format_settings(settings)
		except Exception:
			log(f'BubbleKern parameter sheet: {traceback.format_exc()}', error=True)
		self.dismiss(NSModalResponseOK)

	@objc.python_method
	def dismiss(self, code):
		# A SHEET AND A WINDOW GO AWAY DIFFERENTLY, and which one this is
		# depends on whether there was anything to hang it off.
		try:
			window = self.window()
			parent = window.sheetParent()
			if parent is not None:
				parent.endSheet_returnCode_(window, code)
			window.orderOut_(None)
		except Exception:
			log(f'BubbleKern parameter sheet: {traceback.format_exc()}', error=True)
		_open.discard(self)
