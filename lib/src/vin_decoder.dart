import 'research_models.dart';

final class VinDecodeException implements Exception {
  const VinDecodeException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Parses results produced by a locally hosted VIN catalog.
///
/// OBD Atlas deliberately does not send raw VINs to third-party services.
/// The Proxmox backend will own the standalone decoder database.
final class LocalVinDecoder {
  const LocalVinDecoder();

  static VehicleIdentity parseResult({
    required String vin,
    required Map<String, Object?> result,
  }) {
    final normalized = VinCodec.normalize(vin);
    if (!VinCodec.formatValid(normalized)) {
      throw const VinDecodeException('VIN must contain 17 valid characters.');
    }

    String? text(String key) {
      final value = result[key]?.toString().trim();
      return value == null || value.isEmpty ? null : value;
    }

    final make = text('make');
    final model = text('model');
    final year = int.tryParse(text('modelYear') ?? '');
    if (make == null || model == null || year == null) {
      throw const VinDecodeException(
        'Make, model, or model year was not resolved; manual confirmation is required.',
      );
    }

    return VehicleIdentity(
      vin: normalized,
      make: make,
      model: model,
      modelYear: year,
      generation: text('generation'),
      powertrain: text('powertrain'),
      marketConfiguration: text('marketConfiguration'),
      status: VehicleIdentityStatus.detected,
    );
  }
}
