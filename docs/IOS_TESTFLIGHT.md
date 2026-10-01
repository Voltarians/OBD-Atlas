# OBD Atlas iOS / TestFlight foundation

Permanent bundle identifier:

`com.voltarians.obdatlas`

## Create the iOS runner

The repository does not yet contain Flutter's `ios/` runner. On a Mac with Xcode and Flutter installed, from the repository root run:

```bash
flutter create --platforms=ios --org com.voltarians .
```

Before committing the generated runner, open `ios/Runner.xcworkspace` in Xcode and set:

- Display Name: OBD Atlas
- Bundle Identifier: com.voltarians.obdatlas
- Signing Team: the Voltarians/Apple Developer team
- Automatically manage signing: enabled
- Deployment target: use the current Flutter-supported default unless a tested adapter dependency requires higher

Do not add Bluetooth permissions until the iOS transport actually requires them.

## Transport boundary

The existing `atlas_android_rfcomm` package is Android-specific and must remain so. Do not attempt to use Android RFCOMM/SPP on iOS.

The first iOS release should keep the shared Atlas UI, capture/library logic, and platform-neutral core, while presenting unsupported adapter transports as unavailable. A native iOS transport should be added behind the adapter abstraction after a supported BLE/MFi path is verified on hardware.

## TestFlight

After the iOS runner builds on hardware:

```bash
flutter pub get
flutter analyze
flutter build ipa --release
```

Archive/upload through Xcode or Transporter using the Apple Developer team. Start with TestFlight internal testing before App Store production review.

## Release identity

Android application ID and iOS bundle ID intentionally match:

`com.voltarians.obdatlas`
