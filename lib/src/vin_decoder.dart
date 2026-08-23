import 'dart:convert';

import 'package:http/http.dart' as http;

import 'research_models.dart';

final class VinDecodeException implements Exception {
  const VinDecodeException(this.message);
  final String message;
  @override
  String toString() => message;
}

final class NhtsaVpicDecoder {
  NhtsaVpicDecoder({http.Client? client}) : _client = client ?? http.Client();
  final http.Client _client;

  Future<VehicleIdentity> decode(String vin) async {
    final normalized = VinCodec.normalize(vin);
    if (!VinCodec.formatValid(normalized)) {
      throw const VinDecodeException('VIN must contain 17 valid characters.');
    }
    final uri = Uri.https(
      'vpic.nhtsa.dot.gov',
      '/api/vehicles/DecodeVinValues/$normalized',
      {'format': 'json'},
    );
    final response = await _client.get(uri).timeout(const Duration(seconds: 15));
    if (response.statusCode != 200) {
      throw VinDecodeException(
        'NHTSA VIN service returned HTTP ' + response.statusCode.toString() + '.',
      );
    }
    return parseResponse(vin: normalized, body: response.body);
  }

  static VehicleIdentity parseResponse({required String vin, required String body}) {
    final decoded = jsonDecode(body);
    final results = decoded is Map<String, dynamic> ? decoded['Results'] : null;
    if (results is! List || results.isEmpty || results.first is! Map) {
      throw const VinDecodeException('NHTSA VIN response did not contain a result.');
    }
    final value = Map<String, dynamic>.from(results.first as Map);
    String? text(String key) {
      final result = value[key]?.toString().trim();
      return result == null || result.isEmpty ? null : result;
    }

    final make = text('Make');
    final model = text('Model');
    final year = int.tryParse(text('ModelYear') ?? '');
    if (make == null || model == null || year == null) {
      throw const VinDecodeException(
        'Make, model, or model year was not resolved; manual confirmation is required.',
      );
    }
    final engine = [
      text('EngineModel'),
      if (text('DisplacementL') != null) text('DisplacementL')! + ' L',
    ].whereType<String>().join(' / ');
    final configuration = [
      text('Trim'),
      text('BodyClass'),
      text('VehicleType'),
      text('PlantCountry'),
    ].whereType<String>().join(' / ');

    return VehicleIdentity(
      vin: vin,
      make: make,
      model: model,
      modelYear: year,
      powertrain: engine.isEmpty ? null : engine,
      marketConfiguration: configuration.isEmpty ? null : configuration,
      status: VehicleIdentityStatus.detected,
    );
  }

  void close() => _client.close();
}
