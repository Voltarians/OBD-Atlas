import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:path_provider/path_provider.dart';

class DbcFormatException implements Exception {
  DbcFormatException(this.message);
  final String message;
  @override
  String toString() => 'DBC error: $message';
}

class DbcDocument {
  DbcDocument({required this.sourceName, required this.text, required this.messages, required this.signals, required this.sha256Hex});
  final String sourceName;
  final String text;
  final int messages;
  final int signals;
  final String sha256Hex;

  static DbcDocument parse(String sourceName, String text) {
    final messagePattern = RegExp(r'^BO_\s+(\d+)\s+([A-Za-z_]\w*)\s*:\s*(\d+)\s+\S+\s*$', multiLine: true);
    final signalPattern = RegExp(r'^\s*SG_\s+[A-Za-z_]\w*.*:\s*\d+\|\d+@[01][+-]', multiLine: true);
    final messages = messagePattern.allMatches(text).toList();
    if (messages.isEmpty) throw DbcFormatException('no BO_ messages found');
    for (final match in messages) {
      final rawId = int.parse(match.group(1)!);
      final dlc = int.parse(match.group(3)!);
      if (rawId < 0 || rawId > 0xffffffff) throw DbcFormatException('message ID outside 32-bit range');
      if (dlc < 0 || dlc > 64) throw DbcFormatException('message DLC outside 0..64');
    }
    final normalized = text.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
    return DbcDocument(
      sourceName: sourceName,
      text: normalized.endsWith('\n') ? normalized : '$normalized\n',
      messages: messages.length,
      signals: signalPattern.allMatches(text).length,
      sha256Hex: sha256.convert(utf8.encode(text)).toString(),
    );
  }
}

class StoredDbc {
  const StoredDbc({required this.name, required this.file, required this.messages, required this.signals, required this.sha256Hex});
  final String name;
  final File file;
  final int messages;
  final int signals;
  final String sha256Hex;
}

class DbcStore {
  DbcStore._();
  static final instance = DbcStore._();

  Future<Directory> _directory() async {
    final support = await getApplicationSupportDirectory();
    final directory = Directory('${support.path}${Platform.pathSeparator}dbc');
    await directory.create(recursive: true);
    return directory;
  }

  String _safeName(String value) {
    final safe = value.replaceAll(RegExp(r'[^A-Za-z0-9_.-]'), '_');
    return safe.toLowerCase().endsWith('.dbc') ? safe : '$safe.dbc';
  }

  Future<StoredDbc> importFile(File source) async {
    final text = await source.readAsString();
    final document = DbcDocument.parse(source.uri.pathSegments.last, text);
    final directory = await _directory();
    final target = File('${directory.path}${Platform.pathSeparator}${_safeName(document.sourceName)}');
    await target.writeAsString(document.text, flush: true);
    final metadata = File('${target.path}.json');
    await metadata.writeAsString(jsonEncode({
      'format_version': 1,
      'source_filename': document.sourceName,
      'sha256': document.sha256Hex,
      'messages': document.messages,
      'signals': document.signals,
      'imported_utc': DateTime.now().toUtc().toIso8601String(),
    }), flush: true);
    return StoredDbc(name: target.uri.pathSegments.last, file: target, messages: document.messages, signals: document.signals, sha256Hex: document.sha256Hex);
  }

  Future<List<StoredDbc>> list() async {
    final directory = await _directory();
    final files = directory.listSync().whereType<File>().where((file) => file.path.toLowerCase().endsWith('.dbc')).toList()..sort((a, b) => a.path.compareTo(b.path));
    final result = <StoredDbc>[];
    for (final file in files) {
      final document = DbcDocument.parse(file.uri.pathSegments.last, await file.readAsString());
      result.add(StoredDbc(name: document.sourceName, file: file, messages: document.messages, signals: document.signals, sha256Hex: document.sha256Hex));
    }
    return result;
  }

  Future<File> export(StoredDbc source, String destination) async {
    final document = DbcDocument.parse(source.name, await source.file.readAsString());
    final target = File(destination);
    await target.writeAsString(document.text, flush: true);
    DbcDocument.parse(target.uri.pathSegments.last, await target.readAsString());
    return target;
  }
}
