# Open-source foundation

- [OpenShorts](https://github.com/mutonby/openshorts/tree/1ceb57d77d0429a8f526797287b3529757b31055), MIT core. `skill/scripts/openshorts_windows.py` extracts **only** `build_transcript_windows` unchanged from `clip_selection.py` at commit `1ceb57d77d0429a8f526797287b3529757b31055`. Original notice: [LICENSE.OpenShorts](skill/scripts/LICENSE.OpenShorts). No commercial `cloud/` code is included. It groups subtitle cues for reading; it does not rank our hooks.
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) is invoked as an optional external executable for local speech recognition. Models are obtained separately from the [upstream model host](https://huggingface.co/ggerganov/whisper.cpp); this repository does not distribute binaries or model weights. Model provenance and usage terms remain with their upstream distributors.
- [FFmpeg](https://ffmpeg.org/) is invoked as an external executable for exact trimming, concatenation, fades, audio processing, probing and decode checks. No FFmpeg binary is distributed. Its build configuration determines applicable LGPL/GPL terms.

The agent selection workflow, source-faithful edit plans, review binding, shared installer and rendering CLI are original adaptations in this repository. No OpenShorts service, Gemini SDK, pricing table, virality score or fixed-duration prompt is included.

This repository is private during dogfooding. No license grant is added for original code at this stage; the upstream MIT component retains its own license.
