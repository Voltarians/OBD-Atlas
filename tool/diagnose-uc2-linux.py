#!/usr/bin/env python3
"""Read-only ControlCAN receive diagnostic for one Linux UC2 port.

Run only after disconnecting Atlas from the UC2 devices. This utility never
calls VCI_Transmit. It does not configure SocketCAN or alter vehicle wiring.
The vendor library is an external prerequisite, not bundled by OBD Atlas.
"""

import argparse
import ctypes as C
import os
import sys
import time
from collections import Counter
from pathlib import Path

DEVICE_TYPE = 4  # USBCAN2
TIMING = {
    125000: (0x03, 0x1C),
    250000: (0x01, 0x1C),
    500000: (0x00, 0x1C),
    800000: (0x00, 0x16),
    1000000: (0x00, 0x14),
}
U32_ERROR = 0xFFFFFFFF
BATCH_SIZE = 256
ERROR_BITS = {
    0x0001: 'controller FIFO overflow',
    0x0002: 'controller error alarm',
    0x0004: 'controller error passive',
    0x0008: 'arbitration lost',
    0x0010: 'CAN bus error',
    0x0100: 'device already opened',
    0x0200: 'device open error',
    0x0400: 'device not open',
    0x0800: 'host buffer overflow',
    0x1000: 'device does not exist',
    0x2000: 'kernel library load failure',
    0x4000: 'command failed',
    0x8000: 'buffer creation failure',
}


class VciInitConfig(C.Structure):
    _fields_ = [
        ('AccCode', C.c_uint32),
        ('AccMask', C.c_uint32),
        ('Reserved', C.c_uint32),
        ('Filter', C.c_uint8),
        ('Timing0', C.c_uint8),
        ('Timing1', C.c_uint8),
        ('Mode', C.c_uint8),
    ]


class VciCanObj(C.Structure):
    _fields_ = [
        ('ID', C.c_uint32),
        ('TimeStamp', C.c_uint32),
        ('TimeFlag', C.c_uint8),
        ('SendType', C.c_uint8),
        ('RemoteFlag', C.c_uint8),
        ('ExternFlag', C.c_uint8),
        ('DataLen', C.c_uint8),
        ('Data', C.c_uint8 * 8),
        ('Reserved', C.c_uint8 * 3),
    ]


class VciCanStatus(C.Structure):
    _fields_ = [
        ('ErrInterrupt', C.c_uint8),
        ('regMode', C.c_uint8),
        ('regStatus', C.c_uint8),
        ('regALCapture', C.c_uint8),
        ('regECCapture', C.c_uint8),
        ('regEWLimit', C.c_uint8),
        ('regRECounter', C.c_uint8),
        ('regTECounter', C.c_uint8),
        ('Reserved', C.c_uint32),
    ]


class VciErrInfo(C.Structure):
    _fields_ = [
        ('ErrCode', C.c_uint32),
        ('Passive_ErrData', C.c_uint8 * 3),
        ('ArLost_ErrData', C.c_uint8),
    ]


def find_library(explicit):
    home = Path.home()
    candidates = [
        explicit,
        os.environ.get('OBD_ATLAS_USBCAN_LIB'),
        str(home / 'promethean/rust-can-zlg-lib/library/linux/aarch64/libusbcan.so'),
        '/usr/local/lib/libusbcan.so',
        '/usr/lib/aarch64-linux-gnu/libusbcan.so',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError('ARM64 libusbcan.so not found; use --library PATH.')


def bind(library, name, arguments, result=C.c_uint32):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


def run(args):
    if sys.platform != 'linux':
        raise RuntimeError('This diagnostic requires Linux.')
    if (C.sizeof(VciInitConfig), C.sizeof(VciCanObj),
            C.sizeof(VciCanStatus), C.sizeof(VciErrInfo)) != (16, 24, 16, 8):
        raise RuntimeError('Unexpected ControlCAN structure layout; refusing native calls.')

    path = find_library(args.library)
    print(f'Library: {path}', flush=True)
    library = C.CDLL(path)
    u32 = C.c_uint32
    open_device = bind(library, 'VCI_OpenDevice', [u32, u32, u32])
    close_device = bind(library, 'VCI_CloseDevice', [u32, u32])
    init_can = bind(library, 'VCI_InitCAN', [u32, u32, u32, C.POINTER(VciInitConfig)])
    start_can = bind(library, 'VCI_StartCAN', [u32, u32, u32])
    reset_can = bind(library, 'VCI_ResetCAN', [u32, u32, u32])
    receive_num = bind(library, 'VCI_GetReceiveNum', [u32, u32, u32])
    receive = bind(library, 'VCI_Receive', [u32, u32, u32, C.POINTER(VciCanObj), u32, C.c_int32])
    read_status = bind(library, 'VCI_ReadCANStatus', [u32, u32, u32, C.POINTER(VciCanStatus)])
    read_error = bind(library, 'VCI_ReadErrInfo', [u32, u32, u32, C.POINTER(VciErrInfo)])

    device, channel = args.device, args.channel
    opened = False
    started = False
    total = 0
    counts = Counter()
    samples = 0
    max_pending = 0
    polls = 0
    errors = 0
    receive_results = Counter()
    timing0, timing1 = TIMING[args.bitrate]
    print(f'Device {device} CAN{channel}; {args.bitrate} bit/s; passive/listen-only; {args.seconds:g} seconds', flush=True)
    print(f'Timing0=0x{timing0:02X}, Timing1=0x{timing1:02X}, Mode=1; no transmit calls', flush=True)
    print(f'Receive: batch={args.batch_size}, WaitTime={args.wait_ms} ms', flush=True)

    def report_native_status():
        status = VciCanStatus()
        result = read_status(DEVICE_TYPE, device, channel, C.byref(status))
        if result == 1:
            print('VCI_ReadCANStatus: 1; ' +
                  f'mode=0x{status.regMode:02X}, status=0x{status.regStatus:02X}, '
                  f'REC={status.regRECounter}, TEC={status.regTECounter}, '
                  f'ECC=0x{status.regECCapture:02X}, interrupt=0x{status.ErrInterrupt:02X}', flush=True)
        else:
            print(f'VCI_ReadCANStatus: {result}', flush=True)
        info = VciErrInfo()
        result = read_error(DEVICE_TYPE, device, channel, C.byref(info))
        if result == 1:
            names = [name for bit, name in ERROR_BITS.items() if info.ErrCode & bit]
            print(f'VCI_ReadErrInfo: 1; code=0x{info.ErrCode:08X}; '
                  f'details={", ".join(names) if names else "none reported"}', flush=True)
        else:
            print(f'VCI_ReadErrInfo: {result}', flush=True)

    try:
        result = open_device(DEVICE_TYPE, device, 0)
        print(f'VCI_OpenDevice: {result}', flush=True)
        if result != 1:
            raise RuntimeError('Device open failed. Close Atlas and any other UC2 program, then retry.')
        opened = True
        config = VciInitConfig(0, 0xFFFFFFFF, 0, 1, timing0, timing1, 1)
        result = init_can(DEVICE_TYPE, device, channel, C.byref(config))
        print(f'VCI_InitCAN: {result}', flush=True)
        if result != 1:
            raise RuntimeError('CAN initialization failed. Check the selected physical port and native library.')
        result = start_can(DEVICE_TYPE, device, channel)
        print(f'VCI_StartCAN: {result}', flush=True)
        if result != 1:
            raise RuntimeError('CAN start failed. Check the controller and native library.')
        started = True
        report_native_status()

        buffer = (VciCanObj * args.batch_size)()
        deadline = time.monotonic() + args.seconds
        next_report = time.monotonic() + 2
        while time.monotonic() < deadline:
            pending = receive_num(DEVICE_TYPE, device, channel)
            polls += 1
            if pending == U32_ERROR:
                errors += 1
                print('VCI_GetReceiveNum returned 0xFFFFFFFF (native error)', flush=True)
                break
            max_pending = max(max_pending, pending)
            # A positive timeout and selectable batch size let us distinguish
            # an empty queue from a zero-timeout or batch-handling problem.
            requested = min(max(pending, 1), args.batch_size)
            received = receive(DEVICE_TYPE, device, channel, buffer, requested, args.wait_ms)
            receive_results[received] += 1
            if received == U32_ERROR:
                errors += 1
                print('VCI_Receive returned 0xFFFFFFFF (native error)', flush=True)
                break
            if received > requested:
                errors += 1
                print(f'Invalid native receive count {received} > {requested}', flush=True)
                break
            for frame in buffer[:received]:
                total += 1
                counts[frame.ID] += 1
                if samples < args.samples:
                    samples += 1
                    width = 8 if frame.ExternFlag else 3
                    dlc = min(frame.DataLen, 8)
                    payload = bytes(frame.Data[:dlc]).hex().upper()
                    print(f'RX {frame.ID:0{width}X}#{payload} ext={frame.ExternFlag} rtr={frame.RemoteFlag}', flush=True)
            now = time.monotonic()
            if now >= next_report:
                print(f'Progress: {total} frames, {len(counts)} IDs, max pending {max_pending}, polls {polls}; receive returns {dict(receive_results)}', flush=True)
                next_report = now + 2
            if received == 0 and args.wait_ms == 0:
                time.sleep(0.005)
        print(f'RESULT: {total} frames; {len(counts)} unique IDs; max pending {max_pending}; native errors {errors}', flush=True)
        print(f'Receive return counts: {dict(receive_results)}', flush=True)
        report_native_status()
        if counts:
            print('Top IDs: ' + ', '.join(f'{can_id:08X}={count}' for can_id, count in counts.most_common(10)), flush=True)
        else:
            print('No frames retrieved. A growing pending count with zero receive returns requires investigation of the native library or receive-call behavior.', flush=True)
        return 2 if errors else 0
    finally:
        if opened:
            if started:
                try:
                    print(f'VCI_ResetCAN: {reset_can(DEVICE_TYPE, device, channel)}', flush=True)
                except Exception as error:
                    print(f'Reset error: {error}', flush=True)
            try:
                print(f'VCI_CloseDevice: {close_device(DEVICE_TYPE, device)}', flush=True)
            except Exception as error:
                print(f'Close error: {error}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=int, default=0, help='Native device index, usually 0 or 1')
    parser.add_argument('--channel', type=int, choices=(0, 1), default=0, help='Physical CAN port')
    parser.add_argument('--bitrate', type=int, choices=sorted(TIMING), default=500000)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--samples', type=int, default=12)
    parser.add_argument('--wait-ms', type=int, default=100, help='Native receive timeout in milliseconds (default: 100)')
    parser.add_argument('--batch-size', type=int, default=1, help='Frames requested per receive call (default: 1; maximum: 256)')
    parser.add_argument('--library', help='Explicit path to ARM64 libusbcan.so')
    args = parser.parse_args()
    if args.device < 0 or args.seconds <= 0 or args.samples < 0 or args.wait_ms < 0 or not 1 <= args.batch_size <= BATCH_SIZE:
        parser.error('Device must be nonnegative, seconds positive, samples and timeout nonnegative, and batch size 1 through 256.')
    try:
        return run(args)
    except KeyboardInterrupt:
        print('\nInterrupted; releasing the adapter.', flush=True)
        return 130
    except (OSError, RuntimeError, AttributeError) as error:
        print(f'ERROR: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
