# Native Liquid Glass renderer

Based on [liquidglass](https://github.com/dilmurod3037729-max/liquidglass),
commit `149a841ff9d8a852483dcb76d3b250d9ab427e6e` (MIT; see LICENSE).

Local changes: crop the DirectComposition surface to the Island host, composite
captured windows with premultiplied alpha, limit frame rate, suspend hidden
instances, wake on changes, explicitly shut down the capture thread and GPU,
and soften optical highlights with optional background contrast protection.

The WGC backend no longer initializes the unused Desktop Duplication backend or
allocates its monitor-sized history textures. A single frame-pool buffer is
copied and released in the native callback. Closed pills discover background
layers only within their shape plus the refraction margin; opening surfaces keep
the full host region to preserve morphs. `lg_resource_info` exposes capture counts
and texture-byte estimates for diagnostics; these are not private VRAM residency.

The Qt interface stays in its original window. The D3D11 underlay is transparent
to input and uses per-window Windows Graphics Capture; it is visible in normal
screenshots. Missing capture/GPU support falls back to the existing Windows blur.

The x64 DLL statically links the C++ runtime. No compiler or Python package is
needed on the user's machine beyond the existing Island runtime. Rebuild source
and scripts are preserved in `native/liquid-glass/` in this repository. Run `build.cmd` there
from an x64 Visual Studio developer command prompt.
