#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstring>

#include "../j2534_api.h"

namespace {
constexpr unsigned long kDeviceId = 0x1234;
constexpr unsigned long kChannelId = 0x2345;
constexpr unsigned long kBaudRate = 500000;
}

extern "C" __declspec(dllexport) long WINAPI PassThruOpen(
    void*, unsigned long* pDeviceID) {
  if (pDeviceID == nullptr) return atlas_j2534::ERR_FAILED;
  *pDeviceID = kDeviceId;
  return atlas_j2534::STATUS_NOERROR;
}

extern "C" __declspec(dllexport) long WINAPI PassThruClose(
    unsigned long DeviceID) {
  return DeviceID == kDeviceId ? atlas_j2534::STATUS_NOERROR
                               : atlas_j2534::ERR_INVALID_DEVICE_ID;
}

extern "C" __declspec(dllexport) long WINAPI PassThruConnect(
    unsigned long DeviceID, unsigned long ProtocolID, unsigned long Flags,
    unsigned long BaudRate, unsigned long* pChannelID) {
  if (DeviceID != kDeviceId) return atlas_j2534::ERR_INVALID_DEVICE_ID;
  if (ProtocolID != atlas_j2534::PROTOCOL_ISO15765) {
    return atlas_j2534::ERR_INVALID_PROTOCOL_ID;
  }
  if (BaudRate != kBaudRate) return atlas_j2534::ERR_INVALID_BAUDRATE;
  if (Flags != 0 || pChannelID == nullptr) return atlas_j2534::ERR_FAILED;
  *pChannelID = kChannelId;
  return atlas_j2534::STATUS_NOERROR;
}

extern "C" __declspec(dllexport) long WINAPI PassThruDisconnect(
    unsigned long ChannelID) {
  return ChannelID == kChannelId ? atlas_j2534::STATUS_NOERROR
                                 : atlas_j2534::ERR_INVALID_CHANNEL_ID;
}

extern "C" __declspec(dllexport) long WINAPI PassThruReadVersion(
    unsigned long DeviceID, char* pFirmwareVersion, char* pDllVersion,
    char* pApiVersion) {
  if (DeviceID != kDeviceId || pFirmwareVersion == nullptr ||
      pDllVersion == nullptr || pApiVersion == nullptr) {
    return atlas_j2534::ERR_INVALID_DEVICE_ID;
  }
  strcpy_s(pFirmwareVersion, 80, "FAKE-FW-1.0");
  strcpy_s(pDllVersion, 80, "FAKE-DLL-1.0");
  strcpy_s(pApiVersion, 80, "04.04");
  return atlas_j2534::STATUS_NOERROR;
}

extern "C" __declspec(dllexport) long WINAPI PassThruGetLastError(
    char* pErrorDescription) {
  if (pErrorDescription == nullptr) return atlas_j2534::ERR_FAILED;
  strcpy_s(pErrorDescription, 80, "FAKE_OK");
  return atlas_j2534::STATUS_NOERROR;
}
