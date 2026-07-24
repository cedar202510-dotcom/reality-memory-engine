# Reality Memory Engine

This directory is the single Git repository for the Reality Memory Engine.

## Canonical Paths

- `apps/mobile-app/`: the single user-facing mobile gateway app.
- `apps/rokid-glass-probe/`: the Rokid device-side capture runtime.
- `archive/cxrl-probe/`: archived CXR-L SDK compatibility spike and reference implementation; not a user-facing app.
- `docs/product/Reality-Memory-Engine-PRD-v1.3.md`: the current product and engineering PRD.
- `docs/architecture/`: the current layered technical architecture for capture,
  cloud memory formation, and Agent access.
- `docs/engineering/`: engineering architecture and implementation notes.
- `hardware/ring-sound-sdk/`: ring SDK materials.

In the current CXR-L phase, the mobile app owns user identity, device binding,
policy, encrypted queues, and cloud upload. The target native-glasses
architecture allows the bound glasses runtime to upload through the same cloud
contract, with the mobile app acting as the user client and optional relay.
Hardware-specific code is implemented as adapters or device-side runtimes;
image, short-video, audio, and sensor support must not become separate user
apps. Anything outside `apps/mobile-app/` must be treated as a device runtime,
adapter reference, or archived experiment rather than a second mobile product.

## Architecture Documents

- [Layered architecture](docs/architecture/README.md): current system boundaries,
  deployment routes, shared contracts, and implementation order.
- [Data capture](docs/architecture/01-Data-Capture-Architecture.md): ring, glasses,
  mobile relay, capture runtime, evidence, and direct/fallback transport paths.
- [Memory platform](docs/architecture/02-Memory-Platform-Architecture.md): ingest,
  multimodal parsing, temporal fusion, event store, and state projection.
- [Agent access](docs/architecture/03-Agent-Access-Architecture.md): account grants,
  query, signal subscriptions, correction, deletion, and Demo boundaries.
