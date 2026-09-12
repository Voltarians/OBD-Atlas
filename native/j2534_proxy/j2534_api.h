#pragma once

#include <windows.h>

namespace atlas_j2534 {

using PassThruOpenFn = long(WINAPI*)(void* pName, unsigned long* pDeviceID);
using PassThruCloseFn = long(WINAPI*)(unsigned long DeviceID);
using PassThruConnectFn = long(WINAPI*)(
    unsigned long DeviceID,
    unsigned long ProtocolID,
    unsigned long Flags,
    unsigned long BaudRate,
    unsigned long* pChannelID);
using PassThruDisconnectFn = long(WINAPI*)(unsigned long ChannelID);
using PassThruReadVersionFn = long(WINAPI*)(
    unsigned long DeviceID,
    char* pFirmwareVersion,
    char* pDllVersion,
    char* pApiVersion);
using PassThruGetLastErrorFn = long(WINAPI*)(char* pErrorDescription);

constexpr unsigned long PROTOCOL_ISO15765 = 0x06;

constexpr long STATUS_NOERROR = 0x00;
constexpr long ERR_INVALID_CHANNEL_ID = 0x02;
constexpr long ERR_INVALID_PROTOCOL_ID = 0x03;
constexpr long ERR_FAILED = 0x07;
constexpr long ERR_INVALID_BAUDRATE = 0x19;
constexpr long ERR_INVALID_DEVICE_ID = 0x1A;

}  // namespace atlas_j2534
