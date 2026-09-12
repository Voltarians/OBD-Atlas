#pragma once

#include <windows.h>

namespace atlas_j2534 {

using PassThruOpenFn = long(WINAPI*)(void* pName, unsigned long* pDeviceID);
using PassThruCloseFn = long(WINAPI*)(unsigned long DeviceID);
using PassThruReadVersionFn = long(WINAPI*)(
    unsigned long DeviceID,
    char* pFirmwareVersion,
    char* pDllVersion,
    char* pApiVersion);
using PassThruGetLastErrorFn = long(WINAPI*)(char* pErrorDescription);

constexpr long STATUS_NOERROR = 0x00;
constexpr long ERR_FAILED = 0x07;
constexpr long ERR_INVALID_DEVICE_ID = 0x1A;

}  // namespace atlas_j2534
