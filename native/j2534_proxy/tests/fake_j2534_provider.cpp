#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstring>

#include "../j2534_api.h"

namespace {
constexpr unsigned long kDeviceId = 0x1234;
constexpr unsigned long kChannelId = 0x2345;
constexpr unsigned long kFilterId = 0x3456;
constexpr unsigned long kBaudRate = 500000;

bool MessageMatches(const atlas_j2534::PASSTHRU_MSG* message,
                    const unsigned char (&expected)[4]) {
  if (message == nullptr) return false;
  if (message->ProtocolID != atlas_j2534::PROTOCOL_ISO15765 ||
      message->RxStatus != 0 || message->TxFlags != 0 ||
      message->Timestamp != 0 || message->DataSize != 4 ||
      message->ExtraDataIndex != 0) {
    return false;
  }
  return std::memcmp(message->Data, expected, 4) == 0;
}
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

extern "C" __declspec(dllexport) long WINAPI PassThruStartMsgFilter(
    unsigned long ChannelID, unsigned long FilterType,
    atlas_j2534::PASSTHRU_MSG* pMaskMsg,
    atlas_j2534::PASSTHRU_MSG* pPatternMsg,
    atlas_j2534::PASSTHRU_MSG* pFlowControlMsg,
    unsigned long* pFilterID) {
  if (ChannelID != kChannelId) return atlas_j2534::ERR_INVALID_CHANNEL_ID;
  if (FilterType != atlas_j2534::FLOW_CONTROL_FILTER) {
    return atlas_j2534::ERR_NOT_SUPPORTED;
  }
  if (pMaskMsg == nullptr || pPatternMsg == nullptr ||
      pFlowControlMsg == nullptr || pFilterID == nullptr) {
    return atlas_j2534::ERR_NULL_PARAMETER;
  }
  constexpr unsigned char kMask[4] = {0xFF, 0xFF, 0xFF, 0xFF};
  constexpr unsigned char kPattern[4] = {0x00, 0x00, 0x07, 0xE8};
  constexpr unsigned char kFlow[4] = {0x00, 0x00, 0x07, 0xE0};
  if (!MessageMatches(pMaskMsg, kMask) ||
      !MessageMatches(pPatternMsg, kPattern) ||
      !MessageMatches(pFlowControlMsg, kFlow)) {
    return atlas_j2534::ERR_INVALID_MSG;
  }
  *pFilterID = kFilterId;
  return atlas_j2534::STATUS_NOERROR;
}

extern "C" __declspec(dllexport) long WINAPI PassThruStopMsgFilter(
    unsigned long ChannelID, unsigned long FilterID) {
  if (ChannelID != kChannelId) return atlas_j2534::ERR_INVALID_CHANNEL_ID;
  return FilterID == kFilterId ? atlas_j2534::STATUS_NOERROR
                               : atlas_j2534::ERR_INVALID_FILTER_ID;
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
