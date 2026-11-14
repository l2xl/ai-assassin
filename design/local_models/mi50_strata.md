# `mi50-strata`

[Strata](https://github.com/Niko1221/Strata) is an inference engine with its own launcher, answering an OpenAI-compatible API like
llama.cpp. Its ready-made images (`ghcr.io/niko1221/strata`) cover NVIDIA and newer AMD cards, not `gfx906`; `mixa3607/ML-gfx906`
carries a `strata` subproject that builds the engine for it but publishes no image, so the image is built from it. The preset is a compose project of its own, `assassin-mi50-strata` ([mi50.md](mi50.md)), apart from the llama.cpp one ([mi50_llamacpp.md](mi50_llamacpp.md)).

- **Build.** It needs Docker Buildx and the ROCm base image of the same repository (`rocm/`); then, from `strata/`:
  `STRATA_IMAGE=<name> STRATA_CMAKE_HIP_FLAGS="-mllvm -amdgpu-sched-strategy=max-ilp" ./build-and-push.image.sh`. The script
  pushes to the registry `<name>` points at, so building also takes a registry the server can pull from.
- **Run.** The `x-strata` block of the preset's compose file is what a Strata service merges, as `x-server` does in the llama.cpp preset: image
  `${STRATA_IMAGE:-localhost/strata-gfx906:0.2.3}`, the same cards, groups and read-only models folder — `MODEL_PATH=/models`
  makes Strata read the GGUF files there instead of downloading the model — the `strata-data` volume for its prepared pack and
  state, `memlock` unlimited and `shm_size: 2g` as the engine asks, and a two-minute `stop_grace_period` so a big model unloads
  before docker kills it. No memory limit is set: Strata plans from the whole RAM of the server.
- **Port and key.** A service publishes one port on 127.0.0.1 like every other and sets its own `API_KEY` (16 characters or
  more): the server listens on every address inside the container, so a key is always on, sent as a bearer token; only
  `GET /health` answers without it.
- **Status.** The configuration follows Strata's Docker documentation (v0.2.3.1); the image build and a start on the cards
  have not been run yet.
