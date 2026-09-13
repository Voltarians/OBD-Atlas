$ErrorActionPreference = 'Stop'

Write-Host 'OBD Atlas bootstrap'
Write-Host 'Checking Flutter...'
flutter --version

Write-Host 'Generating Windows and Android platform projects without replacing lib/ or pubspec.yaml...'
flutter create --platforms=android,windows --project-name obd_atlas .

Write-Host 'Resolving packages...'
flutter pub get

Write-Host ''
Write-Host 'Bootstrap complete.'
Write-Host 'Windows: flutter run -d windows'
Write-Host 'Android: flutter devices; flutter run -d <device-id>'
