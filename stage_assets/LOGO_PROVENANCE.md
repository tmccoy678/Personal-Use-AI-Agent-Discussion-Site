# DobeWorks logo provenance

Prepared by Rill (authenticated Codex identity) for Blu Private's integration review. This commit adds artwork only; it does not wire assets into the application.

Taylor's original JPG and supplied duplicate are byte-identical to the existing `dobeworks-logo.jpg`: SHA-256 `7cfd562d0370701fad86c0bfea32515e7becc7ce682fe4db51a666ba9b0dded3`. The original files are unchanged. The source is 1254 × 1254 pixels.

The transparent SVG faithfully traces the source geometry in four tonal path layers using the site's pale blue `#9ad1ed` and graduated opacity. It contains no embedded raster, script, external reference or painted background. Potrace 1.16 used thresholds 240/255, 176/255, 112/255 and 48/255 with `--flat --turdsize 1 --unit 1 --opttolerance 0.15`, following grayscale conversion with ImageMagick 6.9.9-26. No runtime dependency is added. The SVG retains detailed artwork at 2,509,764 bytes (measured gzip encoding: 447,295 bytes); the PNG favicons are exports of this same vector.

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `dobeworks-logo.svg` | 2,509,764 | `a56f5aab211143a64a5360f4b2fd99232ec41c6807a41c57746e23f762f8ed15` |
| `dobeworks-favicon-16.png` | 488 | `015c1a2f70b68d6ae2a2d23b5e92120cba5d3c3654e27756b6a900af455d99a9` |
| `dobeworks-favicon-32.png` | 1,424 | `45fd62c64976486cd7a741b6a4d936a1a791d2290ad673d4e5af70e2d711fa6d` |

## Validation and limits

Source identities, copied asset hashes, SVG structure and transparency were checked. In isolated Chrome 154.0.8037.92, the SVG decoded correctly at 1190- and 390-pixel viewports. Static previews used a 24 × 24 pixel rocket mark and a 40 × 40 pixel footer mark; both had transparent corners and no page overflow. Chrome recognized the 32-pixel favicon. The 16- and 32-pixel PNGs decoded with transparent corners. Desktop, mobile and size-comparison captures were reopened and inspected. Safari was not tested.

Four tonal bands approximate the JPG's continuous grayscale, with one-source-pixel tracing precision. At 16 pixels, individual veins and crosshatching cannot be read; the profile and ring carry the identity. No separate miniature was redrawn. The unchanged JPG remains the detailed artwork reference.

Runtime wiring and current mission-loop integration remain with Blu Private. Full static previews and validation are retained in Taylor's local `rill-stage-logo` handoff folder, outside this commit. No application tests were rerun for this asset-only commit.
