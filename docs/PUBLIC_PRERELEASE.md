# OBD Atlas public alpha installation

OBD Atlas 0.1.0 Alpha 3 is an early research release. Download the file matching the host from the GitHub Releases page.

## Raspberry Pi 5 / Linux ARM64

Install the runtime libraries:

```bash
sudo apt update
sudo apt install -y libgtk-3-0 can-utils bluez
```

Extract `OBD-Atlas-Linux-arm64-v0.1.0-alpha.3.zip`, then run:

```bash
chmod +x obd_atlas
./obd_atlas
```

UC2 users must separately provide the compatible ARM64 `libusbcan.so` and set `OBD_ATLAS_USBCAN_LIB` before starting Atlas. The verified PCG-1 configuration is documented in `docs/PCG1_VERIFIED_FIVE_CHANNEL_CONFIG.md`.

OBDLink MX+ users can pair the adapter with BlueZ and expose its serial service
as `/dev/rfcomm0`. Atlas then provides receive-only `ATMA` monitoring on one
selected channel. See `docs/LINUX_OBDLINK_MX.md` for the exact setup procedure.

## Linux x64

Install `libgtk-3-0` and `can-utils`, extract the x64 ZIP, make `obd_atlas` executable, and run it.

## Windows x64

Extract the entire Windows ZIP and run `obd_atlas.exe`. Do not remove the DLL or `data` directories from the extracted bundle.

## Android

The APK is an unsigned debug build intended for interface testing. Android may require permission to install an app from the browser or file manager used to open it. It does not yet replace the full PCG-1/Linux adapter implementation.

## Safety and support status

Use passive/listen-only capture during public testing. This alpha release is for data collection and research; it must not be relied upon for vehicle control, repair authorization, or safety-critical decisions.
