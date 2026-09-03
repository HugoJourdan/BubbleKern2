# encoding: utf-8
"""Which settings a generate run measures each layer against.

`autoGenerate` is what the Edit menu's 'Generate PolyKern Fingerprints for Selected
Glyphs' calls, and its Option variant hands in the layers of EVERY master at
once. `stored_settings` reads a master's own PolyKern parameter over the
font's, so a run that resolved the settings once - against whichever master
happened to be selected - measured every other master with the wrong gap,
bend and grid. The settings have to follow the layer.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

RESOURCES = (pathlib.Path(__file__).parent.parent / 'PolyKernCentral.glyphsPlugin'
		/ 'Contents' / 'Resources')


def _load(name):
	if str(RESOURCES) not in sys.path:
		sys.path.insert(0, str(RESOURCES))
	spec = importlib.util.spec_from_file_location('pk_' + name, RESOURCES / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	sys.modules['pk_' + name] = module
	spec.loader.exec_module(module)
	return module


store = _load('PKBubbleStore')  # what the menu action calls into

REGULAR = type('Master', (), {'id': 'm1', 'italicAngle': 0, 'xHeight': 500,
		'name': 'Regular', 'ascender': 750, 'descender': -250})()
BOLD = type('Master', (), {'id': 'm2', 'italicAngle': 0, 'xHeight': 500,
		'name': 'Bold', 'ascender': 750, 'descender': -250})()


class UserData(dict):
	def __missing__(self, key):
		return None


class Glyph:
	def __init__(self, name):
		self.name = name

	def beginUndo(self):
		pass

	def endUndo(self):
		pass


class Layer:
	# NOT A GSLayer: `autoGenerate` is handed its layers explicitly, so
	# `chosenLayers` never reaches for the isinstance check that guards a
	# selection.
	def __init__(self, name, master):
		self.width = 600
		self.paths = [object()]
		self.components = []
		self.userData = UserData()
		self.tempData = UserData()
		self.master = master
		self.parent = Glyph(name)

	def associatedFontMaster(self):
		return self.master


class Font:
	upm = 1000

	def __init__(self):
		self.masters = [REGULAR, BOLD]
		self.selectedFontMaster = REGULAR


@pytest.fixture
def measured(monkeypatch):
	"""Record which master each layer was resolved against. -> (font, log)"""
	seen = []

	def settings(font, master, prefs=None):
		seen.append(('settings', master.name))
		return {'gap': None, 'step': 5, 'tolerance': 1, 'max_nodes': 40,
				'slope': 0.0, 'max_inset': 20.0, 'amplitude': 1.0}

	def grid(font, master=None, prefs=None):
		seen.append(('grid', master.name))
		return 0

	def nodes(layer, side, **kwargs):
		seen.append(('measure', layer.parent.name, layer.master.name))
		return [(0, 0), (10, 700)]

	monkeypatch.setattr(store.auto, 'auto_settings', settings)
	monkeypatch.setattr(store.auto, 'resolve_grid', grid)
	monkeypatch.setattr(store.auto, 'auto_bubble_nodes', nodes)
	monkeypatch.setattr(store, 'recordBox', lambda layer, side: None)
	return Font(), seen


# --- Which master a layer is measured against -------------------------------


def test_every_layer_is_measured_against_its_own_master(measured):
	font, seen = measured
	layers = [Layer('a', REGULAR), Layer('a', BOLD)]
	store.autoGenerate(font, True, layers=layers)
	assert [row for row in seen if row[0] == 'measure'] == [
			('measure', 'a', 'Regular'), ('measure', 'a', 'Bold')]
	# Both masters' settings were read, not the selected one's twice.
	assert sorted(row[1] for row in seen if row[0] == 'settings') == ['Bold', 'Regular']


def test_the_settings_are_read_once_per_master(measured):
	font, seen = measured
	layers = [Layer(name, master) for master in (REGULAR, BOLD)
			for name in ('a', 'b', 'c')]
	store.autoGenerate(font, True, layers=layers)
	assert len([row for row in seen if row[0] == 'settings']) == 2
	assert len([row for row in seen if row[0] == 'grid']) == 2
	assert len([row for row in seen if row[0] == 'measure']) == 6


def test_a_single_master_run_still_reads_that_master(measured):
	font, seen = measured
	store.autoGenerate(font, True, layers=[Layer('a', REGULAR)])
	assert ('settings', 'Regular') in seen
	assert ('grid', 'Regular') in seen


def test_a_layer_with_no_master_of_its_own_falls_back_to_the_selected_one(measured):
	font, seen = measured
	layer = Layer('a', REGULAR)
	layer.associatedFontMaster = lambda: None
	store.autoGenerate(font, True, layers=[layer])
	assert ('settings', 'Regular') in seen, 'the selected master stood in'
