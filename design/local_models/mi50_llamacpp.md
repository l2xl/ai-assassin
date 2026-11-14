# `mi50-llamacpp`

The llama.cpp preset of the MI50 cards ([mi50.md](mi50.md)), the compose project `assassin-mi50-llamacpp`. The image of every service of it is the gfx906 build of [llama.cpp](https://github.com/ggml-org/llama.cpp)
published by mixa3607 (`mixa3607/ML-gfx906`) as `docker.io/mixa3607/llama.cpp-gfx906:<ver>-rocm-10.1`. It is built for
the deprecated `gfx906` architecture alone and runs on no other card.

- **Compose file.** The `x-server` block a service merges holds the image, the cards and the models folder of [mi50.md](mi50.md), and a health check against the server's `/health`.
- **Tag.** The `-rocm-10.1` flavor has daily builds, so `<ver>` is a release tag taken from Docker Hub and pinned in the
  `x-server` anchor of the compose file; moving to a newer build is a change of that one line, then `assassin-models up mi50-llamacpp`.
- **Server profiles and router.** The image carries optional YAML/JSON model presets (*server profiles*) and a router mode
  that loads models on demand from the models folder, which is how the server's own `llama-server` container runs.
- **Other flavors.** `-rocm-10.1-mxxm` and newer ROCm builds exist; the preset takes the plain `-rocm-10.1` flavor the server already holds.
