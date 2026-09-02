# encoding: utf-8
"""Carrying the preferences across the rename.

The plugin was called BubbleKern, and everything it remembers between launches
was saved under that name - the kerning presets and favourites most of all,
which are a person's own work rather than a setting that can be defaulted
again. Renaming the keys without moving the values would have thrown all of it
away silently, which is the failure this pins.
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


auto = _load('PKAutoBubble')

PRESETS_OLD = 'com.Tosche.BubbleKern.presetsDic'
PRESETS_NEW = 'com.Tosche.PolyKern.presetsDic'
FRAME_OLD = 'NSWindow Frame com.Tosche.BubbleKernKerner.mainwindow'
FRAME_NEW = 'NSWindow Frame com.Tosche.PolyKernKerner.mainwindow'


@pytest.fixture
def prefs():
	return {PRESETS_OLD: {'A V': -80}, 'com.Tosche.BubbleKern.favDic': {'fav': 1},
			FRAME_OLD: '100 200 300 400', 'com.apple.something': 'not ours'}


# --- What comes across ------------------------------------------------------


def test_the_presets_survive_the_rename(prefs):
	assert auto.migrate_preferences(prefs) == 3
	assert prefs[PRESETS_NEW] == {'A V': -80}
	assert prefs['com.Tosche.PolyKern.favDic'] == {'fav': 1}


def test_a_key_no_constant_names_still_comes_across(prefs):
	# vanilla saves the window frame itself; nothing here enumerates it.
	auto.migrate_preferences(prefs)
	assert prefs[FRAME_NEW] == '100 200 300 400'


def test_nobody_elses_preferences_are_touched(prefs):
	auto.migrate_preferences(prefs)
	assert prefs['com.apple.something'] == 'not ours'
	assert set(prefs) == {PRESETS_OLD, PRESETS_NEW, FRAME_OLD, FRAME_NEW,
			'com.Tosche.BubbleKern.favDic', 'com.Tosche.PolyKern.favDic',
			'com.apple.something', auto.MIGRATED_PREF}


def test_the_old_keys_are_left_where_they_are(prefs):
	# The old plugin may still be installed beside this one.
	auto.migrate_preferences(prefs)
	assert prefs[PRESETS_OLD] == {'A V': -80}


# --- Running it more than once ----------------------------------------------


def test_it_runs_once(prefs):
	assert auto.migrate_preferences(prefs) == 3
	assert auto.migrate_preferences(prefs) == 0


def test_a_value_already_set_under_the_new_name_wins(prefs):
	prefs[PRESETS_NEW] = {'mine': 1}
	auto.migrate_preferences(prefs)
	assert prefs[PRESETS_NEW] == {'mine': 1}, 'never written over'


def test_nothing_to_carry_is_not_an_error():
	prefs = {'com.apple.something': 1}
	assert auto.migrate_preferences(prefs) == 0
	assert prefs[auto.MIGRATED_PREF] is True
