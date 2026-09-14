/// A vehicle type is not a VIN, a person, or a particular ECU calibration.
/// Never infer a model from CAN IDs or a user-supplied VIN alone.
class VehicleIdentity {
  const VehicleIdentity({
    required this.make,
    required this.model,
    required this.modelYear,
    this.generation,
    this.platform,
    this.source = 'user_selected',
    this.vin,
  });

  final String make;
  final String model;
  final int? modelYear;
  final int? generation;
  final String? platform;
  final String source;
  final String? vin;

  static const unknown = VehicleIdentity(
    make: 'Unknown', model: 'Unknown', modelYear: null, source: 'unknown',
  );

  static String _slug(String value) => value.toLowerCase().trim()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '-')
      .replaceAll(RegExp(r'^-+|-+$'), '');

  static String _make(String value) {
    switch (_slug(value)) {
      case 'chevy': case 'chevrolet': return 'Chevrolet';
      case 'opel': return 'Opel';
      case 'vauxhall': return 'Vauxhall';
      case 'cadillac': return 'Cadillac';
      default: return value.trim();
    }
  }

  static String _model(String make, String value) {
    final slug = _slug(value);
    if (slug == 'volt' && make == 'Chevrolet') return 'Volt';
    if (slug == 'ampera' && (make == 'Opel' || make == 'Vauxhall')) return 'Ampera';
    if (slug == 'elr' && make == 'Cadillac') return 'ELR';
    return value.trim();
  }

  factory VehicleIdentity.selected({
    required String make, required String model, required int modelYear,
    int? generation, String? vin,
  }) {
    final canonicalMake = _make(make);
    final canonicalModel = _model(canonicalMake, model);
    final isVolt = canonicalMake == 'Chevrolet' && canonicalModel == 'Volt';
    final isAmpera = (canonicalMake == 'Opel' || canonicalMake == 'Vauxhall') && canonicalModel == 'Ampera';
    final isElr = canonicalMake == 'Cadillac' && canonicalModel == 'ELR';
    int? resolvedGeneration = generation;
    String? platform;
    if (isVolt) {
      if (modelYear >= 2011 && modelYear <= 2015) {
        resolvedGeneration = 1;
      } else if (modelYear >= 2016 && modelYear <= 2019) {
        resolvedGeneration = 2;
      } else {
        throw FormatException('Volt model year must be 2011–2019.');
      }
    } else if (isAmpera) {
      if (modelYear < 2012 || modelYear > 2015) {
        throw FormatException('This catalog covers the 2012–2015 Ampera.');
      }
      resolvedGeneration = 1;
    } else if (isElr) {
      if (modelYear < 2014 || modelYear > 2016) {
        throw FormatException('ELR model year must be 2014–2016.');
      }
      resolvedGeneration = 1;
    }
    if (isVolt || isAmpera || isElr) {
      if (generation != null && generation != resolvedGeneration) {
        throw FormatException('Generation conflicts with the selected model year.');
      }
      platform = 'GM Voltec';
    }
    final result = VehicleIdentity(
      make: canonicalMake, model: canonicalModel, modelYear: modelYear,
      generation: resolvedGeneration, platform: platform,
      vin: vin?.trim().toUpperCase(),
    );
    result.validate();
    return result;
  }

  bool get isUnknown => source == 'unknown' ||
      (_slug(make) == 'unknown' && _slug(model) == 'unknown');
  bool get isChevroletVolt => make == 'Chevrolet' && model == 'Volt' &&
      (generation == 1 || generation == 2);
  String get vehicleType => isUnknown ? 'unidentified' :
      '${_slug(make)}-${_slug(model)}${generation == null ? '' : '-gen$generation'}';
  String get yearKey => modelYear?.toString() ?? 'unknown-year';
  String get displayName => isUnknown ? 'Unidentified vehicle' :
      '${modelYear ?? 'Unknown year'} $make $model${generation == null ? '' : ' • Gen $generation'}';

  void validate() {
    if (isUnknown) {
      if (vin != null && vin!.isNotEmpty) throw const FormatException('Unidentified sessions cannot carry a VIN.');
      return;
    }
    for (final value in [make, model]) {
      if (value.trim().isEmpty || value.length > 80 || _slug(value).isEmpty) {
        throw const FormatException('Make and model must contain valid names.');
      }
    }
    if (modelYear == null || modelYear! < 1886 || modelYear! > 2100) {
      throw const FormatException('Select a valid model year.');
    }
    if (generation != null && (generation! < 1 || generation! > 99)) {
      throw const FormatException('Invalid generation.');
    }
    if (vin != null && vin!.isNotEmpty &&
        !RegExp(r'^[A-HJ-NPR-Z0-9]{17}$').hasMatch(vin!)) {
      throw const FormatException('A VIN must contain 17 valid characters.');
    }
    if (source != 'user_selected' && source != 'vin_decoded' &&
        source != 'curator_verified' && source != 'unknown') {
      throw const FormatException('Unknown identity source.');
    }
  }

  /// The VIN is deliberately never part of a capture manifest or path.
  /// A user-entered VIN is not evidence of a successful VIN decode.
  Map<String, dynamic> toJson({bool includeVin = false}) => {
    'make': make, 'model': model, 'model_year': modelYear,
    'generation': generation, 'platform': platform,
    'vehicle_type': vehicleType,
    'identity_source': source,
    'identity_status': source == 'unknown' ? 'unknown' :
        source == 'user_selected' ? 'unverified' : 'verified',
    if (includeVin && vin != null && vin!.isNotEmpty) 'vin': vin,
  };

  factory VehicleIdentity.fromJson(Map<String, dynamic> json) {
    int? number(Object? value) => value is int ? value : int.tryParse('$value');
    final result = VehicleIdentity(
      make: (json['make'] ?? 'Unknown').toString(),
      model: (json['model'] ?? 'Unknown').toString(),
      modelYear: number(json['model_year'] ?? json['year']),
      generation: json['generation'] == null ? null : number(json['generation']),
      platform: json['platform']?.toString(),
      source: (json['identity_source'] ?? 'user_selected').toString(),
      vin: json['vin']?.toString(),
    );
    result.validate();
    if (!result.isUnknown) {
      final canonical = VehicleIdentity.selected(
        make: result.make, model: result.model, modelYear: result.modelYear!,
        generation: result.generation, vin: result.vin,
      );
      if (canonical.make != result.make || canonical.model != result.model ||
          canonical.generation != result.generation) {
        throw const FormatException('Stored vehicle identity conflicts with the catalog.');
      }
    }
    return result;
  }

  /// Retain an explicitly decoded identity as a distinct evidence source.
  /// Decoding itself is performed by a trusted VIN-decoder integration later.
  VehicleIdentity withDecodedVin(String decodedVin) {
    final normalized = decodedVin.trim().toUpperCase();
    if (vin != null && vin!.isNotEmpty && vin != normalized) {
      throw const FormatException('VIN decode conflicts with the local vehicle.');
    }
    final result = VehicleIdentity(
      make: make, model: model, modelYear: modelYear,
      generation: generation, platform: platform, source: 'vin_decoded', vin: normalized,
    );
    result.validate();
    return result;
  }
}

/// Explicit upload policy. A client-side status flag is never authority for
/// public admission; the server must independently verify the vehicle type.
class VehicleRoutingPolicy {
  const VehicleRoutingPolicy({this.allowedPublicTypes = const {'chevrolet-volt-gen1', 'chevrolet-volt-gen2'}});
  final Set<String> allowedPublicTypes;
  bool allowsPublicType(VehicleIdentity identity) =>
      !identity.isUnknown && allowedPublicTypes.contains(identity.vehicleType);
  String localDirectory(VehicleIdentity identity) =>
      '${identity.vehicleType}/${identity.yearKey}';
}
