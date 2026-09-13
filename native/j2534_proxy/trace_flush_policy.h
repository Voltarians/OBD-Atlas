#pragma once

#include <windows.h>

BOOL WINAPI AtlasTraceWriteFile(
    HANDLE hFile,
    LPCVOID lpBuffer,
    DWORD nNumberOfBytesToWrite,
    LPDWORD lpNumberOfBytesWritten,
    LPOVERLAPPED lpOverlapped);

BOOL WINAPI AtlasTraceFlushFileBuffers(HANDLE hFile);

// Test-only observability for the off-vehicle durability-policy acceptance test.
unsigned long long AtlasTracePhysicalFlushCountForTesting();
void AtlasTraceResetFlushPolicyForTesting();

#ifndef ATLAS_TRACE_FLUSH_POLICY_IMPLEMENTATION
#define WriteFile AtlasTraceWriteFile
#define FlushFileBuffers AtlasTraceFlushFileBuffers
#endif
