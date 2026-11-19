# Changelog

## 1.0.0

Initial public release.

- Background removal locally with RobustVideoMatting (RVM) or through fal.ai / VEED.
- Timeline multi-selection on Resolve 21.0.4+, with a clip-color fallback for older versions.
- Frame-accurate cutting for variable-frame-rate footage, including iPhone sources.
- Correct source-to-timeline frame conversion when frame rates differ.
- Automatic duration checks and length correction when placing results in the timeline.
- macOS support, including Apple Silicon acceleration through PyTorch MPS.

Test status: the local backend has been successfully tested on Windows 11 with an NVIDIA RTX 4070 Super and DaVinci Resolve Studio. macOS and fal.ai have not yet been tested in practice.
