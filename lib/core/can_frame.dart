class CanFrame {
  const CanFrame({
    required this.timestamp,
    required this.id,
    required this.data,
    this.extended = false,
    this.remote = false,
    this.bus = 'can0',
  });

  final DateTime timestamp;
  final int id;
  final List<int> data;
  final bool extended;
  final bool remote;
  final String bus;

  int get dlc => data.length;

  String get idHex => id.toRadixString(16).toUpperCase().padLeft(extended ? 8 : 3, '0');

  String get dataHex => data.map((byte) => byte.toRadixString(16).toUpperCase().padLeft(2, '0')).join(' ');

  String toCandump({DateTime? epoch}) {
    final seconds = timestamp.microsecondsSinceEpoch / 1000000.0;
    final payload = remote ? 'R$dlc' : data.map((b) => b.toRadixString(16).padLeft(2, '0')).join('').toUpperCase();
    return '(${seconds.toStringAsFixed(6)}) $bus $idHex#$payload';
  }
}
