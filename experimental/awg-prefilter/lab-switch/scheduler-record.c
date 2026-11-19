// SPDX-License-Identifier: MIT
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <evntrace.h>
#include <stdio.h>
#include <stddef.h>
#include <wchar.h>

#ifndef EVENT_TRACE_SYSTEM_LOGGER_MODE
#define EVENT_TRACE_SYSTEM_LOGGER_MODE 0x02000000
#endif

typedef struct {
    EVENT_TRACE_PROPERTIES props;
    wchar_t name[96];
    wchar_t path[MAX_PATH];
} TraceProperties;

int wmain(int argc, wchar_t **argv) {
    if ((argc != 4 && argc != 6) || wcslen(argv[1]) >= MAX_PATH) {
        fwprintf(stderr, L"Usage: scheduler-record TRACE.etl STOP_FILE MAX_SECONDS [START_FILE STATUS_LOG]\n");
        return 2;
    }
    wchar_t *end = NULL;
    unsigned long duration = wcstoul(argv[3], &end, 10);
    if (end == argv[3] || *end || duration < 1 || duration > 900) return 2;
    if (GetFileAttributesW(argv[1]) != INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(argv[2]) != INVALID_FILE_ATTRIBUTES) return 2;
    FILE *status = stdout;
    if (argc == 6) {
        status = _wfopen(argv[5], L"wx");
        if (!status) return 2;
        fprintf(status, "AUTHORIZED pid=%lu\n", (unsigned long)GetCurrentProcessId());
        fflush(status);
        ULONGLONG gate_deadline = GetTickCount64() + 900000;
        while (GetFileAttributesW(argv[4]) == INVALID_FILE_ATTRIBUTES) {
            if (GetFileAttributesW(argv[2]) != INVALID_FILE_ATTRIBUTES ||
                GetTickCount64() >= gate_deadline) {
                fputs("CANCELLED before trace start\n", status);
                fclose(status);
                return 0;
            }
            Sleep(100);
        }
    }
    TraceProperties p = {0};
    wchar_t name[96];
    swprintf(name, 96, L"ColdwireScheduler-%lu", (unsigned long)GetCurrentProcessId());
    wcscpy(p.path, argv[1]);
    p.props.Wnode.BufferSize = sizeof(p);
    p.props.Wnode.Flags = WNODE_FLAG_TRACED_GUID;
    p.props.Wnode.ClientContext = 1;
    p.props.LogFileMode = EVENT_TRACE_SYSTEM_LOGGER_MODE | EVENT_TRACE_FILE_MODE_SEQUENTIAL;
    p.props.EnableFlags = EVENT_TRACE_FLAG_THREAD | EVENT_TRACE_FLAG_CSWITCH |
                          EVENT_TRACE_FLAG_DISPATCHER;
    p.props.BufferSize = 64;
    p.props.MinimumBuffers = 64;
    p.props.MaximumBuffers = 256;
    p.props.MaximumFileSize = 2048;
    p.props.FlushTimer = 1;
    p.props.LoggerNameOffset = offsetof(TraceProperties, name);
    p.props.LogFileNameOffset = offsetof(TraceProperties, path);
    TRACEHANDLE handle = 0;
    ULONG rc = StartTraceW(&handle, name, &p.props);
    if (rc != ERROR_SUCCESS) {
        fprintf(argc == 6 ? status : stderr, "StartTrace: Win32 %lu\n", (unsigned long)rc);
        if (argc == 6) fclose(status);
        return 1;
    }
    LARGE_INTEGER start, finish, frequency;
    QueryPerformanceCounter(&start);
    QueryPerformanceFrequency(&frequency);
    fprintf(status, "READY pid=%lu qpc_ticks=%lld frequency=%lld\n", (unsigned long)GetCurrentProcessId(),
           (long long)start.QuadPart, (long long)frequency.QuadPart);
    fflush(status);
    ULONGLONG deadline = GetTickCount64() + (ULONGLONG)duration * 1000;
    while (GetTickCount64() < deadline &&
           GetFileAttributesW(argv[2]) == INVALID_FILE_ATTRIBUTES) Sleep(50);

    QueryPerformanceCounter(&finish);
    rc = ControlTraceW(handle, NULL, &p.props, EVENT_TRACE_CONTROL_STOP);
    fprintf(status, "STOP status=%lu qpc_ticks=%lld events_lost=%lu file_buffers_lost=%lu\n",
           (unsigned long)rc, (long long)finish.QuadPart,
           (unsigned long)p.props.EventsLost, (unsigned long)p.props.LogBuffersLost);
    if (argc == 6) fclose(status);
    return rc != ERROR_SUCCESS;
}
