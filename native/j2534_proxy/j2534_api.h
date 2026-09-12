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

struct SCONFIG {
  unsigned long Parameter;
  unsigned long Value;
};

struct SCONFIG_LIST {
  unsigned long NumOfParams;
  SCONFIG* ConfigPtr;
};

struct SBYTE_ARRAY {
  unsigned long NumOfBytes;
  unsigned char* BytePtr;
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
using PassThruIoctlFn = long(WINAPI*)(
    unsigned long ChannelID,
    unsigned long IoctlID,
    void* pInput,
    void* pOutput);
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

constexpr unsigned long IOCTL_GET_CONFIG = 0x01;
constexpr unsigned long IOCTL_SET_CONFIG = 0x02;
constexpr unsigned long IOCTL_READ_VBATT = 0x03;
constexpr unsigned long IOCTL_FIVE_BAUD_INIT = 0x04;
constexpr unsigned long IOCTL_FAST_INIT = 0x05;
constexpr unsigned long IOCTL_CLEAR_TX_BUFFER = 0x07;
constexpr unsigned long IOCTL_CLEAR_RX_BUFFER = 0x08;
constexpr unsigned long IOCTL_CLEAR_PERIODIC_MSGS = 0x09;
constexpr unsigned long IOCTL_CLEAR_MSG_FILTERS = 0x0A;
constexpr unsigned long IOCTL_CLEAR_FUNCT_MSG_LOOKUP_TABLE = 0x0B;
constexpr unsigned long IOCTL_ADD_TO_FUNCT_MSG_LOOKUP_TABLE = 0x0C;
constexpr unsigned long IOCTL_DELETE_FROM_FUNCT_MSG_LOOKUP_TABLE = 0x0D;
constexpr unsigned long IOCTL_READ_PROG_VOLTAGE = 0x0E;

constexpr unsigned long CONFIG_DATA_RATE = 0x01;
constexpr unsigned long CONFIG_LOOPBACK = 0x03;

constexpr long STATUS_NOERROR = 0x00;
constexpr long ERR_NOT_SUPPORTED = 0x01;
constexpr long ERR_INVALID_CHANNEL_ID = 0x02;
constexpr long ERR_INVALID_PROTOCOL_ID = 0x03;
constexpr long ERR_NULL_PARAMETER = 0x04;
constexpr long ERR_INVALID_IOCTL_VALUE = 0x05;
constexpr long ERR_INVALID_FLAGS = 0x06;
constexpr long ERR_FAILED = 0x07;
constexpr long ERR_DEVICE_NOT_CONNECTED = 0x08;
constexpr long ERR_TIMEOUT = 0x09;
constexpr long ERR_INVALID_MSG = 0x0A;
constexpr long ERR_INVALID_IOCTL_ID = 0x0F;
constexpr long ERR_INVALID_FILTER_ID = 0x16;
constexpr long ERR_INVALID_BAUDRATE = 0x19;
constexpr long ERR_INVALID_DEVICE_ID = 0x1A;

}  // namespace atlas_j2534
