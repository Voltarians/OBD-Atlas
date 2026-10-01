# Google Play internal release

OBD Atlas Android application ID: `com.voltarians.obdatlas`

The release build intentionally refuses to use the debug signing key.

## Local signing setup

Create the upload keystore locally. Do not commit it:

```powershell
keytool -genkeypair -v -keystore $env:USERPROFILE\obd-atlas-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

Create `android/key.properties` locally:

```properties
storePassword=YOUR_STORE_PASSWORD
keyPassword=YOUR_KEY_PASSWORD
keyAlias=upload
storeFile=C:\\Users\\Monroe\\obd-atlas-upload.jks
```

Both `key.properties` and `*.jks` are excluded by `android/.gitignore`.

## Build the Play bundle

```powershell
flutter clean
flutter pub get
flutter build appbundle --release
```

Expected bundle:

`build\app\outputs\bundle\release\app-release.aab`

Upload that bundle to the Google Play Console Internal testing track first. Enable Play App Signing when creating the app/release. Keep the upload keystore backed up securely; later updates must be signed with the same upload key unless the Play Console upload key is reset.
