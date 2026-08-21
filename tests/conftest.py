"""Glyphs, faked well enough to import the plugin.

BKCommonLogic and BKTool both `from GlyphsApp import ...` at module level, and
BKTool looks up an ObjC class of Glyphs' own while it is being read. Neither
exists outside the app, so both are stood in for here - once, before any test
module is imported, because a stub installed twice is two different `GSLayer`
classes and `isinstance` picks the wrong one.
"""

from __future__ import annotations

import sys
import types

import objc

# ANY CLASS OF GLYPHS' OWN, INVENTED ON DEMAND. Only the handful the plugin
# actually reasons about are declared below; the rest just have to exist.
_lookUpClass = objc.lookUpClass


def _lookUpAnything(name):
	try:
		return _lookUpClass(name)
	except Exception:
		return type(name, (), {})


objc.lookUpClass = _lookUpAnything


class _Permissive(type):
	# A CLASS OF GLYPHS' OWN ANSWERS TO ANYTHING. The plugin registers
	# callbacks and asks the app about itself while it is being imported, and
	# none of that has to work here - it only has to not raise.
	def __getattr__(cls, name):
		if name.startswith('__'):
			raise AttributeError(name)
		return lambda *a, **k: None


class _AnyClass(metaclass=_Permissive):
	def __getattr__(self, name):
		if name.startswith('__'):
			raise AttributeError(name)
		return lambda *a, **k: None


def _anything(name):
	if name.startswith('__'):
		raise AttributeError(name)
	return _Permissive(name, (_AnyClass,), {}) if name[:1].isupper() else (
			lambda *a, **k: None)


_glyphs = types.ModuleType('GlyphsApp')
_glyphs.__getattr__ = _anything
_glyphs.Glyphs = types.SimpleNamespace(font=None, defaults={}, versionNumber=3.2,
		addCallback=lambda *a: None, removeCallback=lambda *a: None,
		redraw=lambda: None,
		localize=lambda strings: (strings.get('en') if hasattr(strings, 'get')
			else strings))
_glyphs.GSAlignmentDisable = -1
# DECLARED, NOT INVENTED: the plugin asks `isinstance(layer, GSLayer)`, so the
# fakes have to be able to subclass the very class it imported.
_glyphs.GSLayer = _Permissive('GSLayer', (_AnyClass,), {})
_glyphs.GSControlLayer = _Permissive('GSControlLayer', (_AnyClass,), {})

_plugins = types.ModuleType('GlyphsApp.plugins')
_plugins.__getattr__ = _anything
_plugins.SelectTool = type('SelectTool', (), {})
_glyphs.plugins = _plugins

sys.modules.setdefault('GlyphsApp', _glyphs)
sys.modules.setdefault('GlyphsApp.plugins', _plugins)
