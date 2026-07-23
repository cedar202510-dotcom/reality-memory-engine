# Reality Memory Engine

This directory is the single Git repository for the Reality Memory Engine.

## Canonical Paths

- `apps/mobile-app/`: the single user-facing mobile gateway app.
- `apps/rokid-glass-probe/`: the Rokid device-side capture runtime.
- `apps/cxrl-probe/`: an SDK compatibility spike and reference implementation.
- `docs/product/Reality-Memory-Engine-PRD-v1.3.md`: the current product and engineering PRD.
- `docs/engineering/`: engineering architecture and implementation notes.
- `hardware/ring-sound-sdk/`: ring SDK materials.

The mobile app owns user identity, device binding, policy, encrypted queues, and
cloud upload. Hardware-specific code is implemented as adapters or device-side
runtimes; image, short-video, audio, and sensor support must not become separate
user apps.
