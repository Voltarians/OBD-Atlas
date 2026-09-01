import '../core/can_frame.dart';

enum AtlasAdapterState { disconnected, connecting, connected, error }

abstract class AtlasAdapter {
  String get id;
  String get displayName;
  String get transport;
  AtlasAdapterState get state;
  Stream<CanFrame> get frames;
  Stream<AtlasAdapterState> get states;

  Future<void> connect();
  Future<void> disconnect();
}
