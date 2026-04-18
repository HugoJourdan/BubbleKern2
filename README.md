# BubbleKern2
A set of GlyphsApp plugins that allows you to kern fonts in a more visual way. Unlike the original BubbleKern, it is based on the polygonal data format for the balance of data/computation efficiency and user experience.

Currently in alpha state.
![Title image](BubbleKernHeader.png)

## Installation
Install BubbleKernCentral.glyphsPlugin by double-clicking it (assuming you already have GlyphsApp).

## Plugins
- BubbleKern Tool: A new tool to draw bubbles. Each glyph contains two polygonal bubbles on the left and right.
- BubbleKern Kerner: A dialogue-based plugin to generate kerning data or export font with experimental *BBLH* table.

## Test files
- BK Test Serif: my open-source sample roman file with pre-drawn bubbles.
- BKTestSerif-Regular.otf: the font file with BBLH table.
- BubbleKernTester.html: currently the only place where you can test dynamic kerning using *BBLH* table.