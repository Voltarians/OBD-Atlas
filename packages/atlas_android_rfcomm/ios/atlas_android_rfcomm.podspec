Pod::Spec.new do |s|
  s.name             = 'atlas_android_rfcomm'
  s.version          = '0.1.0'
  s.summary          = 'OBD Atlas Bluetooth transport helpers.'
  s.description      = <<-DESC
Android RFCOMM transport plus an iOS Core Bluetooth BR/EDR GATT discovery probe.
                       DESC
  s.homepage         = 'https://github.com/Voltarians/OBD-Atlas'
  s.license          = { :type => 'MIT' }
  s.author           = { 'Voltarians' => 'opensource@voltarians.org' }
  s.source           = { :path => '.' }
  s.source_files     = 'Classes/**/*'
  s.dependency 'Flutter'
  s.platform         = :ios, '13.0'
  s.swift_version    = '5.0'
end
