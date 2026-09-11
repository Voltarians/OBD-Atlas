import 'dart:convert';

class VehicleSignalCatalog {
  VehicleSignalCatalog._(this.catalogId, this.signals);

  final String catalogId;
  final List<Map<String, Object?>> signals;

  static VehicleSignalCatalog fromJson(String source) {
    final root = jsonDecode(source);
    if (root is! Map<String, dynamic> || root['schemaVersion'] != 1) {
      throw const FormatException('Unsupported vehicle signal catalog');
    }
    final catalogId = root['catalogId'];
    final rawSignals = root['signals'];
    if (catalogId is! String || rawSignals is! List) {
      throw const FormatException('Invalid vehicle signal catalog');
    }

    final signals = rawSignals.map((raw) {
      if (raw is! Map<String, dynamic> ||
          raw['name'] is! String ||
          !const {'confirmed', 'candidate'}.contains(raw['status']) ||
          raw['channel'] is! int ||
          raw['canId'] is! String ||
          raw['extended'] is! bool ||
          raw['decode'] is! Map<String, dynamic>) {
        throw const FormatException('Invalid signal entry');
      }
      return Map<String, Object?>.unmodifiable(raw);
    }).toList(growable: false);

    return VehicleSignalCatalog._(catalogId, signals);
  }
}
