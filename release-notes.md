# OBD Atlas 0.1.0 Alpha 4

Fourth public test build of the offline-first OBD Atlas vehicle research application.

## Included

- Windows x64 application bundle
- Linux x64 application bundle
- Raspberry Pi/Linux ARM64 application bundle
- Android debug APK for interface evaluation
- Five-channel PCG-1 capture support and event-correlated signal discovery
- Initial machine-readable Chevrolet Volt Gen-1 signal catalog
- Linux ARM64 OBDLink MX+ support through BlueZ RFCOMM
- Receive-only `STMA` fast capture with compact standard and extended CAN-frame parsing
- ARM64 RFCOMM crash isolation through a standard-library helper process
- MX+ `STMA` fast monitoring with compact output for increased capture throughput

## Important limitations

- This is an alpha research build, not a finished diagnostic product.
- Use passive/listen-only CAN operation. Do not transmit on a vehicle network unless you understand the safety consequences.
- The Android APK is a debug/test build and does not yet provide the complete PCG-1 adapter path.
- The UC2 ARM64 driver is external and is not redistributed in this release.
- The MX+ provides one-bus monitoring and does not replace the five-channel PCG-1 adapter configuration.
- Gen-1 Volt signal definitions were verified on one test vehicle and require cross-model-year validation.

See `docs/PUBLIC_PRERELEASE.md` for installation and startup instructions.
