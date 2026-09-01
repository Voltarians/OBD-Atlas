import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

class AtlasLocalStore {
  AtlasLocalStore._();
  static final AtlasLocalStore instance = AtlasLocalStore._();

  Directory? _root;

  Future<Directory> rootDirectory() async {
    if (_root != null) return _root!;
    final docs = await getApplicationDocumentsDirectory();
    final dir = Directory('${docs.path}${Platform.pathSeparator}OBD Atlas');
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
    _root = dir;
    return dir;
  }

  Future<Directory> logsDirectory() async {
    final root = await rootDirectory();
    final dir = Directory('${root.path}${Platform.pathSeparator}logs');
    if (!await dir.exists()) {
      await dir.create(recursive: true);
    }
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
      final text = await file.readAsString();
      final decoded = jsonDecode(text);
      return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    } catch (_) {
      return <String, dynamic>{};
    }
  }

  Future<void> writeJson(String name, Map<String, dynamic> data) async {
    final file = await _jsonFile(name);
    final tmp = File('${file.path}.tmp');
    await tmp.writeAsString(
      const JsonEncoder.withIndent('  ').convert(data),
      flush: true,
    );
    if (await file.exists()) await file.delete();
    await tmp.rename(file.path);
  }

  Future<List<FileSystemEntity>> listLogs() async {
    final dir = await logsDirectory();
    final entries = await dir.list().toList();
    entries.sort((a, b) => b.statSync().modified.compareTo(a.statSync().modified));
    return entries;
  }

  Future<File> createCaptureFile() async {
    final dir = await logsDirectory();
    final now = DateTime.now();
    String two(int value) => value.toString().padLeft(2, '0');
    final stamp = '${now.year}${two(now.month)}${two(now.day)}_${two(now.hour)}${two(now.minute)}${two(now.second)}';
    return File('${dir.path}${Platform.pathSeparator}atlas_capture_$stamp.log');
  }

  Future<File> importLog(File source) async {
    final dir = await logsDirectory();
    final baseName = source.uri.pathSegments.last;
    var destination = File('${dir.path}${Platform.pathSeparator}$baseName');
    if (await destination.exists()) {
      final stamp = DateTime.now().toIso8601String().replaceAll(':', '-');
      destination = File('${dir.path}${Platform.pathSeparator}${stamp}_$baseName');
    }
    return source.copy(destination.path);
  }
}
