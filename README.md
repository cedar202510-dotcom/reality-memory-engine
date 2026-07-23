# Reality Memory Engine

This directory is the single Git repository for the Reality Memory Engine.

## Canonical Paths

- `apps/mobile-app/`: the single user-facing mobile gateway app.
- `apps/rokid-glass-probe/`: the Rokid device-side capture runtime.
- `archive/cxrl-probe/`: archived CXR-L SDK compatibility spike and reference implementation; not a user-facing app.
- `docs/product/Reality-Memory-Engine-PRD-v1.3.md`: the current product and engineering PRD.
- `docs/engineering/`: engineering architecture and implementation notes.
- `hardware/ring-sound-sdk/`: ring SDK materials.

The mobile app owns user identity, device binding, policy, encrypted queues, and
cloud upload. Hardware-specific code is implemented as adapters or device-side
runtimes; image, short-video, audio, and sensor support must not become separate
user apps. Anything outside `apps/mobile-app/` must be treated as a device
runtime, adapter reference, or archived experiment rather than a second mobile
product.
