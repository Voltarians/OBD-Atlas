class CanFrame {
  const CanFrame({
    required this.timestamp,
    required this.id,
    required this.data,
    this.extended = false,
    this.remote = false,
    this.channel = 1,
    String? bus,
  }) : bus = bus ?? 'can${channel - 1}';

  final DateTime timestamp;
  final int id;
  final List<int> data;
  final bool extended;
  final bool remote;

  /// Atlas vehicle-bus channel, 1 through 5.
  final int channel;

  /// Stable textual bus tag written to capture files (can0 through can4 by default).
  final String bus;

  int get dlc => data.length;

  String get channelLabel => 'CH$channel';

  String get idHex => id.toRadixString(16).toUpperCase().padLeft(extended ? 8 : 3, '0');

  String get dataHex => data.map((byte) => byte.toRadixString(16).toUpperCase().padLeft(2, '0')).join(' ');

  String toCandump({DateTime? epoch}) {
    final seconds = timestamp.microsecondsSinceEpoch / 1000000.0;
    final payload = remote ? 'R$dlc' : data.map((b) => b.toRadixString(16).padLeft(2, '0')).join('').toUpperCase();
    return '(${seconds.toStringAsFixed(6)}) $bus $idHex#$payload';
  }
}
