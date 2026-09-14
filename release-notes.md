# OBD Atlas 0.1.0 Alpha 5

Fifth public test build of the offline-first OBD Atlas vehicle research application.

## Included

- Windows x64 application bundle
- Linux x64 application bundle
- Raspberry Pi/Linux ARM64 application bundle
- Android debug APK for interface evaluation
- Vehicle-confirmed Chevrolet Volt Gen-1 HPCM2 contactor/precharge state decoder
- Gen-1 precharge diagnostic analyzer with startup-sequence timing and failure classification
- High-confidence capture-derived CAN 0x228 DC-link/output-voltage candidate, explicitly retained as candidate-only pending independent validation
- GDS2 dynamic-data discovery wrapper and configurable periodic UUDT scheduler
- GM-tool evidence-bundle correlation with sensitive-data redaction
- Synchronized click and optional voice event markers for capture correlation
- Five-channel PCG-1 capture support and event-correlated signal discovery
- Linux ARM64 OBDLink MX+ support through BlueZ RFCOMM
- Built-in isolated UC2/VCX J2534 round-trip bench validation
- Registry-driven Atlas GDS2 bench simulator

## Important limitations

- This is an alpha research build, not a finished diagnostic product.
- The precharge analyzer is core diagnostic logic and is not yet a complete guided user-interface workflow.
- CAN 0x228 bytes 2-3 at 0.0125 V/count remains a capture-derived candidate until independently validated against GDS2, service data, or a controlled external measurement.
- Use passive/listen-only CAN operation on vehicle networks.
- Active UC2/VCX validation and GDS2 simulation are restricted to an isolated, vehicle-disconnected bench.
- SecurityAccess, programming, write, and actuator services remain blocked by default.
- The Android APK is a debug/test build and does not yet provide the complete PCG-1 adapter path.
- The UC2 ARM64 driver is external and is not redistributed.
- MX+ remains a one-bus interface and does not replace the five-channel PCG-1 configuration.
- Gen-1 Volt signal definitions require cross-model-year validation.

See `docs/PUBLIC_PRERELEASE.md` for installation and startup instructions.
