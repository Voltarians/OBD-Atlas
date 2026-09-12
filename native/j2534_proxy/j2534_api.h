#pragma once

#include <windows.h>

namespace atlas_j2534 {

struct PASSTHRU_MSG {
  unsigned long ProtocolID;
  unsigned long RxStatus;
  unsigned long TxFlags;
  unsigned long Timestamp;
  unsigned long DataSize;
  unsigned long ExtraDataIndex;
  unsigned char Data[4128];
};

using PassThruOpenFn = long(WINAPI*)(void* pName, unsigned long* pDeviceID);
using PassThruCloseFn = long(WINAPI*)(unsigned long DeviceID);
using PassThruConnectFn = long(WINAPI*)(
    unsigned long DeviceID,
    unsigned long ProtocolID,
    unsigned long Flags,
    unsigned long BaudRate,
    unsigned long* pChannelID);
using PassThruDisconnectFn = long(WINAPI*)(unsigned long ChannelID);
using PassThruStartMsgFilterFn = long(WINAPI*)(
    unsigned long ChannelID,
    unsigned long FilterType,
    PASSTHRU_MSG* pMaskMsg,
    PASSTHRU_MSG* pPatternMsg,
    PASSTHRU_MSG* pFlowControlMsg,
    unsigned long* pFilterID);
using PassThruStopMsgFilterFn = long(WINAPI*)(
    unsigned long ChannelID,
    unsigned long FilterID);
using PassThruReadMsgsFn = long(WINAPI*)(
    unsigned long ChannelID,
    PASSTHRU_MSG* pMsg,
    unsigned long* pNumMsgs,
    unsigned long Timeout);
using PassThruWriteMsgsFn = long(WINAPI*)(
    unsigned long ChannelID,
    PASSTHRU_MSG* pMsg,
    unsigned long* pNumMsgs,
    unsigned long Timeout);
using PassThruReadVersionFn = long(WINAPI*)(
    unsigned long DeviceID,
    char* pFirmwareVersion,
    char* pDllVersion,
    char* pApiVersion);
using PassThruGetLastErrorFn = long(WINAPI*)(char* pErrorDescription);

constexpr unsigned long PROTOCOL_ISO15765 = 0x06;

constexpr unsigned long PASS_FILTER = 0x01;
constexpr unsigned long BLOCK_FILTER = 0x02;
constexpr unsigned long FLOW_CONTROL_FILTER = 0x03;

constexpr long STATUS_NOERROR = 0x00;
constexpr long ERR_NOT_SUPPORTED = 0x01;
constexpr long ERR_INVALID_CHANNEL_ID = 0x02;
constexpr long ERR_INVALID_PROTOCOL_ID = 0x03;
constexpr long ERR_NULL_PARAMETER = 0x04;
constexpr long ERR_INVALID_FLAGS = 0x06;
constexpr long ERR_FAILED = 0x07;
constexpr long ERR_DEVICE_NOT_CONNECTED = 0x08;
constexpr long ERR_TIMEOUT = 0x09;
constexpr long ERR_INVALID_MSG = 0x0A;
constexpr long ERR_INVALID_FILTER_ID = 0x16;
constexpr long ERR_INVALID_BAUDRATE = 0x19;
constexpr long ERR_INVALID_DEVICE_ID = 0x1A;

}  // namespace atlas_j2534
