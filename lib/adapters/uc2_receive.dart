/// Receive policy validated on PCG-1 with the ARM64 ControlCAN library.
///
/// The September 6 vehicle diagnostic retrieved 13,638 frames using Len=1
/// and WaitTime=100 ms. The previous larger, zero-timeout requests returned
/// zero while the native queue grew. The individual cause has not yet been
/// isolated, so keep the confirmed combination until separately tested.
///
/// This helper is synchronous and contains no native calls. Call it from a
/// single owner of the UC2 library; do not poll a device concurrently.
const int uc2ReceiveBurstLimit = 64;
const int uc2ReceiveWaitMs = 100;
const int _nativeError = 0xffffffff;

int drainUc2Receive({
  required int Function() pending,
  required int Function(int requested, int waitMs) receive,
  required void Function() onFrame,
  required String source,
  int maxFrames = uc2ReceiveBurstLimit,
  int waitMs = uc2ReceiveWaitMs,
}) {
  if (maxFrames < 1 || waitMs < 0) {
    throw ArgumentError('Invalid UC2 receive burst or timeout.');
  }

  var total = 0;
  while (total < maxFrames) {
    final queued = pending();
    if (queued == _nativeError) {
      throw StateError('$source: VCI_GetReceiveNum failed.');
    }
    if (queued == 0) break;
    if (queued < 0) {
      throw StateError('$source: invalid native pending count $queued.');
    }

    // Never request a large batch: Len=1, WaitTime=100 is the verified path.
    // A positive timeout is used only after the native queue reports data.
    final received = receive(1, waitMs);
    if (received == _nativeError) {
      throw StateError('$source: VCI_Receive failed.');
    }
    if (received == 0) break;
    if (received != 1) {
      throw StateError('$source: invalid native receive count $received.');
    }
    onFrame();
    total++;
  }
  return total;
}
