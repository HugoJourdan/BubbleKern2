# encoding: utf-8

# THE ROOT OF ALL POLYKERN-RELATED PLUGINS. Both classes below are principal
# classes of this one bundle, and Glyphs instantiates each at launch.
#
# Named BubbleKern until 2026-09-02, and internally BubbleKern 4 before that.
# The number went with the name; there is no PolyKern 2 or 4.

from PKKerner import PolyKernKerner
from PKTool import PolyKernTool

# THE NEWEST ONE LAST, AND GUARDED. Every principal class of a bundle is
# imported by this one file, so an import error in any of them takes the others
# down with it - and the tool IS the plugin. The preview is the one part whose
# absence leaves everything else working: an entry missing from the View menu,
# against a plugin missing altogether.
try:
	from PKPairsPreview import PolyKernPairs
except Exception:
	import traceback
	from PKCommonLogic import log
	log(f'PolyKernPairs could not be loaded: {traceback.format_exc()}', error=True)
