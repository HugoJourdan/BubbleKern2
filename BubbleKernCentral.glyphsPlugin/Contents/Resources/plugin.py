# encoding: utf-8

# THE ROOT OF ALL BUBBLEKERN-RELATED PLUGINS.
# IT'S CALLED BUBBLEKERN '4' FOR INTERNAL PURPOSE ONLY.
# I'LL CHANGE '4' TO 2 EVENTUALLY.

from __future__ import division, print_function, unicode_literals
import objc
from GlyphsApp import Glyphs, EDIT_MENU
from GlyphsApp.plugins import GeneralPlugin
from AppKit import NSMenuItem

from BKKerner import BubbleKernKerner
from BKReporter import ShowKernBubbles4
from BKTool import BubbleKernTool4

class BubbleKern4(GeneralPlugin):

	@objc.python_method
	def settings(self):
		self.name = Glyphs.localize({
			'en': 'BubbleKern 4',
		})

	@objc.python_method
	def start(self):
		self.reporter = ShowKernBubbles4.alloc().init()
		self.tool = BubbleKernTool4.alloc().init()
		# mainMenu = Glyphs.mainMenu()
		self.kerner = BubbleKernKerner.alloc().init()
		# newMenuItem = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(self.name, self.showWindow_, "")
		# newMenuItem.setTarget_(self)
		# Glyphs.menu[EDIT_MENU].append(newMenuItem)

	# def showWindow_(self, sender):
		"""Do something like show a window """
		# pass

	@objc.python_method
	def __file__(self):
		"""Please leave this method unchanged"""
		return __file__
