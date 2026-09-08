import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:path_provider/path_provider.dart';

import 'vehicle_identity.dart';

class AtlasLocalStore {
  AtlasLocalStore._();
  AtlasLocalStore.forDirectory(this._root);
  static final AtlasLocalStore instance = AtlasLocalStore._();

  Directory? _root;
  VehicleIdentity? _vehicle;
  final Map<String, Map<String, dynamic>> _activeManifests = {};
  static const routing = VehicleRoutingPolicy();

  VehicleIdentity get selectedVehicle => _vehicle ?? VehicleIdentity.unknown;

  Future<Directory> rootDirectory() async {
    if (_root != null) return _root!;
    final docs = await getApplicationDocumentsDirectory();
    final dir = Directory('${docs.path}${Platform.pathSeparator}OBD Atlas');
    if (!await dir.exists()) await dir.create(recursive: true);
    _root = dir;
    return dir;
  }

  Future<Directory> logsDirectory() async {
    final root = await rootDirectory();
    final dir = Directory('${root.path}${Platform.pathSeparator}logs');
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir;
  }

  Future<File> _jsonFile(String name) async {
    final root = await rootDirectory();
    return File('${root.path}${Platform.pathSeparator}$name.json');
  }

  Future<Map<String, dynamic>> readJson(String name) async {
    final file = await _jsonFile(name);
    if (!await file.exists()) return <String, dynamic>{};
    try {
      final decoded = jsonDecode(await file.readAsString());
      return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    } catch (_) {
      return <String, dynamic>{};
    }
  }

  Future<void> _writeFileAtomically(File file, String text) async {
    final tmp = File('${file.path}.tmp');
    await tmp.writeAsString(text, flush: true);
    await tmp.rename(file.path);
  }

  Future<void> writeJson(String name, Map<String, dynamic> data) async {
    await _writeFileAtomically(
      await _jsonFile(name), const JsonEncoder.withIndent('  ').convert(data),
    );
  }

  Future<VehicleIdentity> loadVehicle() async {
    if (_vehicle != null) return _vehicle!;
    final data = await readJson('vehicle_profile');
    if (data.isEmpty) return _vehicle = VehicleIdentity.unknown;
    try {
      return _vehicle = VehicleIdentity.fromJson(data);
    } catch (_) {
      return _vehicle = VehicleIdentity.unknown;
    }
  }

  Future<void> selectVehicle(VehicleIdentity vehicle) async {
    vehicle.validate();
    await writeJson('vehicle_profile', vehicle.toJson(includeVin: true));
    _vehicle = vehicle;
  }

  Future<List<FileSystemEntity>> listLogs() async {
    final dir = await logsDirectory();
    final entries = await dir.list(recursive: true, followLinks: false)
        .where((entity) => entity is File && !entity.path.endsWith('.tmp'))
        .toList();
    entries.sort((a, b) => b.statSync().modified.compareTo(a.statSync().modified));
    return entries;
  }

  String _newSessionId() {
    final now = DateTime.now().toUtc();
    String two(int value) => value.toString().padLeft(2, '0');
    final stamp = '${now.year}${two(now.month)}${two(now.day)}T'
        '${two(now.hour)}${two(now.minute)}${two(now.second)}'
        '${now.millisecond.toString().padLeft(3, '0')}Z';
    final random = Random.secure();
    final suffix = List<int>.generate(8, (_) => random.nextInt(256))
        .map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
    return 'atlas_${stamp}_$suffix';
  }

  File manifestFor(File log) => File('${log.path.substring(0, log.path.length - 4)}.session.json');

  Future<void> _saveManifest(File log, Map<String, dynamic> manifest) async {
    await _writeFileAtomically(
      manifestFor(log), const JsonEncoder.withIndent('  ').convert(manifest),
    );
  }

  Future<File> createCaptureFile() async {
    final vehicle = await loadVehicle();
    final root = await logsDirectory();
    final id = _newSessionId();
    final dir = Directory('${root.path}${Platform.pathSeparator}'
        '${routing.localDirectory(vehicle).replaceAll('/', Platform.pathSeparator)}'
        '${Platform.pathSeparator}$id');
    await dir.create(recursive: true);
    final file = File('${dir.path}${Platform.pathSeparator}$id.log');
    await file.create();
    final started = DateTime.now().toUtc().toIso8601String();
    final manifest = <String, dynamic>{
      'schema': 'voltec-atlas.capture-session.v1',
      'identity_schema': 'obd-atlas.vehicle-identity.v1',
      'session_id': id,
      'capture_type': 'passive_multi_bus_can',
      'vehicle': vehicle.toJson(),
      'time': {'metadata_started_utc': started},
      'capture_status': {
        'complete_shutdown': false,
        'termination_reason': 'recording',
        'total_frames': 0,
      },
      'buses': <Map<String, dynamic>>[],
      'files': [
        {'name': '$id.log', 'role': 'candump_log', 'format': 'candump_-L'}
      ],
      'ingestion': {
        'retain_original_interface_names': true,
        'public_upload_authorized': false,
        'identity_review_required': true,
      },
    };
    await _saveManifest(file, manifest);
    _activeManifests[file.path] = manifest;
    return file;
  }

  /// Called only after the writer has stopped. A failed/incomplete capture is
  /// retained as evidence, not advertised as a successful capture.
  Future<void> completeCapture(File file, int frames, Object? error) async {
    final manifest = _activeManifests[file.path];
    if (manifest == null) return;
    final status = manifest['capture_status'] as Map<String, dynamic>;
    final buses = <String, Map<String, dynamic>>{};
    final ids = <String, Set<int>>{};
    final pattern = RegExp(
      r'^\((\d+(?:\.\d+)?)\)\s+(\S+)\s+([0-9A-Fa-f]{1,8})#([0-9A-Fa-f]*)$',
    );
    var counted = 0;
    var malformed = 0;
    double? firstTimestamp;
    double? lastTimestamp;
    await for (final line in file.openRead().transform(utf8.decoder).transform(const LineSplitter())) {
      final match = pattern.firstMatch(line.trim());
      if (match == null || match.group(4)!.length.isOdd || match.group(4)!.length > 16) {
        malformed++;
        continue;
      }
      final timestamp = double.tryParse(match.group(1)!);
      if (timestamp == null || !timestamp.isFinite) {
        malformed++;
        continue;
      }
      final bus = match.group(2)!;
      final id = int.parse(match.group(3)!, radix: 16);
      firstTimestamp = firstTimestamp == null || timestamp < firstTimestamp ? timestamp : firstTimestamp;
      lastTimestamp = lastTimestamp == null || timestamp > lastTimestamp ? timestamp : lastTimestamp;
      final entry = buses.putIfAbsent(bus, () => {
        'logged_interface': bus,
        'atlas_bus': 'unassigned',
        'mode': 'passive_capture',
        'frames': 0,
        'captured': true,
      });
      entry['frames'] = (entry['frames'] as int) + 1;
      ids.putIfAbsent(bus, () => <int>{}).add(id);
      counted++;
    }
    for (final entry in buses.entries) {
      entry.value['unique_arbitration_ids'] = ids[entry.key]!.length;
    }
    manifest['buses'] = buses.values.toList();
    final valid = error == null && malformed == 0 && counted == frames;
    status['complete_shutdown'] = valid;
    status['termination_reason'] = error != null ? 'capture_error' :
        malformed > 0 ? 'malformed_capture' :
        counted != frames ? 'frame_count_mismatch' : 'user_stop';
    status['total_frames'] = counted;
    status['malformed_frames'] = malformed;
    status['writer_frame_count'] = frames;
    final time = manifest['time'] as Map<String, dynamic>;
    time['metadata_ended_utc'] = DateTime.now().toUtc().toIso8601String();
    if (firstTimestamp != null && lastTimestamp != null) {
      time['first_can_frame_utc'] = DateTime.fromMicrosecondsSinceEpoch(
          (firstTimestamp * 1000000).round(), isUtc: true).toIso8601String();
      time['last_can_frame_utc'] = DateTime.fromMicrosecondsSinceEpoch(
          (lastTimestamp * 1000000).round(), isUtc: true).toIso8601String();
      time['can_duration_seconds'] = lastTimestamp - firstTimestamp;
    }
    final entry = (manifest['files'] as List).first as Map<String, dynamic>;
    entry['size_bytes'] = await file.length();
    entry['sha256'] = (await sha256.bind(file.openRead()).first).toString();
    await _saveManifest(file, manifest);
    _activeManifests.remove(file.path);
  }

  Future<File> importLog(File source) async {
    final dir = Directory('${(await logsDirectory()).path}${Platform.pathSeparator}imports${Platform.pathSeparator}unclassified');
    await dir.create(recursive: true);
    final baseName = source.uri.pathSegments.last;
    var destination = File('${dir.path}${Platform.pathSeparator}$baseName');
    if (await destination.exists()) {
      final stamp = DateTime.now().toIso8601String().replaceAll(':', '-');
      destination = File('${dir.path}${Platform.pathSeparator}${stamp}_$baseName');
    }
    return source.copy(destination.path);
  }
}
