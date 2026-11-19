# Simple BG Remover

One-click background removal for DaVinci Resolve on Windows and macOS. Simple BG Remover extracts people from selected timeline clips using local [RobustVideoMatting (RVM)](https://github.com/PeterL1n/RobustVideoMatting) or the paid fal.ai / VEED cloud backend, renders ProRes 4444 with alpha, and places the results on a free video track above the originals. Instead of running Magic Mask on every clip during playback, you render once and edit with real-time-friendly transparent media. Actual playback performance depends on your hardware, storage, and footage.

**Test status:** the local backend has been successfully tested on Windows 11 with an NVIDIA RTX 4070 Super and DaVinci Resolve Studio. **macOS and the fal.ai backend have not yet been tested in practice.** Compatibility with the free edition of Resolve is not verified.

## Requirements

- DaVinci Resolve with scripting support; tested with **Studio**. Resolve **21.0.4 or newer** is required for timeline multi-selection through `Timeline.GetSelectedClips`. Older versions can use the Orange clip-color fallback.
- **Python 3.12**, available as `python` on Windows or `python3` on macOS.
- **ffmpeg and ffprobe**. The installers help install ffmpeg via Windows Package Manager (`winget`) or Homebrew on macOS.
- Local processing: preferably an NVIDIA GPU with a compatible CUDA driver, or Apple Silicon using PyTorch MPS. CPU fallback is available but slow. The Windows installer uses the PyTorch CUDA 12.4 package index.
- Internet access for installation and the initial RVM code/model download; a fal.ai account and your own API key for cloud processing.
- Enough free disk space for large ProRes 4444 output files.

## Installation

Download and extract the release ZIP, or clone this repository. Keep the project folder in a permanent location: the generated Resolve menu scripts reference it by absolute path. If you move it, rerun `setup_menu.py` using the project's virtual-environment Python.

In Resolve, open **Preferences > System > General** and set **External scripting using** to **Local**.

### Windows

1. Install Python 3.12 from [python.org](https://www.python.org/downloads/) and enable **Add python.exe to PATH**. Ensure `python --version` reports Python 3.12.
2. Double-click `install_windows.bat`. If ffmpeg is missing, the installer attempts to install it with `winget`.
3. The installer creates `venv`, installs dependencies and the Resolve menu scripts, and runs a local-backend self-test that downloads RVM.
4. Review the terminal output for errors, then restart Resolve.

If ffmpeg is not found after installation, reopen your terminal or set `ffmpeg_dir` in `config.json` to the folder containing both ffmpeg and ffprobe.

### macOS (not yet tested)

1. Install Python 3.12 and verify that `python3 --version` reports Python 3.12.
2. Install [Homebrew](https://brew.sh) if you want the installer to install ffmpeg automatically. Alternatively, install ffmpeg and ffprobe yourself.
3. Open Terminal in the project folder and run `bash install_mac.command`.
4. The installer creates `venv`, installs dependencies and the Resolve menu scripts, and runs the RVM self-test. Review its output and restart Resolve.

On Apple Silicon the worker selects MPS when available; otherwise it falls back to CPU. Installers run the local self-test even if you intend to use only fal.ai.

## Usage

1. Open a project and timeline. Save a backup before processing important work.
2. Select the video clips to process (Resolve 21.0.4+). On older versions, give the target clips the **Orange** clip color.
3. Choose **Workspace > Scripts > Hintergrund entfernen (lokal)** for local processing, or **Hintergrund entfernen (fal.ai)** for cloud processing. Depending on Resolve's menu layout, look under **Edit**.
4. Wait for rendering to finish. With the default cloud settings, confirm the estimated cost in the worker terminal before processing starts.
5. Simple BG Remover imports the results into the **BG entfernt** media-pool bin and places them above the originals. By default it disables the original video items and colors them Teal. Place your replacement background below the transparent results.

Selection priority is: selected timeline video items, then clips with the configured marking color, then the clip under the playhead. Without a selection, existing Orange clips take precedence over the playhead clip.

Output files are saved in `_BG_entfernt` next to each source video. Existing results may be reused. The bridge checks placed clip duration and attempts automatic length correction; review any warnings and check synchronization. Rendered results contain video only, not copied source audio.

## Configuration

Edit `config.json` before running a menu command. Defaults:

| Option | Default | Meaning |
| --- | --- | --- |
| `mark_color` | `"Orange"` | Clip color used when timeline selection is unavailable or empty. |
| `done_color` | `"Teal"` | Color applied to original items after placement. |
| `handles_frames` | `0` | Extra source frames before and after the selected range; the worker also renders a small internal reserve for length correction. |
| `disable_original` | `true` | Disable original video items after placing results. |
| `reuse_existing` | `true` | Reuse an existing output with the expected filename; set to `false` to rerender after changing model settings. |
| `output_subfolder` | `"_BG_entfernt"` | Output folder next to the source media. |
| `media_pool_bin` | `"BG entfernt"` | Destination media-pool bin. |
| `ffmpeg_dir` | `""` | Optional folder containing ffmpeg and ffprobe; empty uses automatic discovery. |
| `local.model` | `"resnet50"` | RVM architecture: `resnet50` for quality or `mobilenetv3` for speed. |
| `local.fp16` | `true` | Use half precision on NVIDIA CUDA; MPS and CPU use float32. Disable if CUDA output shows artifacts. |
| `local.downsample_ratio` | `null` | Automatic RVM downsampling, or a manually selected ratio greater than 0 and at most 1. |
| `fal.api_key` | `""` | Your fal.ai key; empty falls back to `FAL_KEY`. Never commit a real key. |
| `fal.model` | `"veed/video-background-removal/fast"` | Fast endpoint; alternatively `veed/video-background-removal`. |
| `fal.refine_edges` | `true` | Request foreground-edge refinement. |
| `fal.confirm_cost` | `true` | Prompt for confirmation before cloud processing. The built-in estimate may be outdated. |
| `fal.max_chunk_seconds` | `55` | Target maximum duration of each uploaded segment. |

### fal.ai credentials and pricing

Set `fal.api_key` locally in `config.json`, or leave it empty and supply the **`FAL_KEY` environment variable** to the Resolve/worker process. A key in the config takes precedence. If using an environment variable, ensure Resolve inherits it; setting it in an unrelated terminal is not enough. Prefer `FAL_KEY` when working in a Git checkout, because `config.json` is tracked.

Cloud processing is paid. Consult the current fal.ai pricing for the [Fast endpoint](https://fal.ai/models/veed/video-background-removal/fast#pricing) or the [standard endpoint](https://fal.ai/models/veed/video-background-removal#pricing). The terminal estimate is informational, not a billing guarantee.

### Privacy

**The fal.ai backend uploads video segments to an external service.** Before processing footage containing identifiable people, including client footage, you must have the necessary legal basis and comply with applicable data-protection requirements and the provider's terms. Do not upload confidential footage without authorization.

**The local backend does not upload your footage.** It downloads RVM code and model weights when needed, then processes video on your machine.

## Known limitations

- **HDR / HLG / Dolby Vision:** the processing path assumes SDR / BT.709. Convert HDR footage to SDR first; automatic HDR tone mapping is not provided.
- **Speed changes:** retiming and speed ramps are not reproduced automatically. Check synchronization and duration warnings.
- **Frame rates:** frame-aware cutting includes variable-frame-rate sources such as iPhone footage, and the bridge accounts for different source and timeline frame rates. Verify the results, especially with retimed or unusual media.
- **Storage and playback:** ProRes 4444 files are large. Plan sufficient disk space and fast storage; real-time playback is not guaranteed on every system.
- **Source types:** compound clips, generators, and items without a directly accessible video file are skipped.
- **Untested paths:** macOS/MPS, macOS/CPU, and fal.ai have not been tested in practice. Windows/CPU and the free Resolve edition are also not verified.

## Troubleshooting and bug reports

Inspect the worker terminal and `last_error.log` in the project folder when available. Use the bug-report template and include OS, GPU, Resolve version, backend, source/timeline frame rates, and a redacted error log. Remove API keys, personal paths, signed URLs, and other sensitive data. **Do not attach client videos or identifiable-person footage.**

## License and credits

Simple BG Remover is licensed under **GPL-3.0-only**; see [LICENSE](LICENSE). It is provided without warranty.

- [RobustVideoMatting](https://github.com/PeterL1n/RobustVideoMatting) by PeterL1n and contributors — [GNU GPL v3](https://github.com/PeterL1n/RobustVideoMatting/blob/master/LICENSE); downloaded at runtime, not bundled here.
- [FFmpeg](https://ffmpeg.org/) — video decoding, encoding, and probing. Its license depends on the build; see [FFmpeg's legal information](https://ffmpeg.org/legal.html).
- [fal.ai / VEED Video Background Removal](https://fal.ai/models/veed/video-background-removal) — optional paid cloud backend, subject to the provider's terms.

This project is not affiliated with, endorsed by, or sponsored by Blackmagic Design, fal.ai, or VEED. All trademarks belong to their respective owners.

## Deutsch

Die deutsche Installations- und Bedienungsanleitung steht in [ANLEITUNG.md](ANLEITUNG.md). Die lokale Windows-Variante wurde getestet; macOS und fal.ai sind noch nicht in der Praxis getestet. Aktuelle Datenschutz-, Preis- und Testhinweise findest du oben in diesem README.
