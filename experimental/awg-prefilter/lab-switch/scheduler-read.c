// SPDX-License-Identifier: MIT
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const GUID thread_provider = {0x3d6fa8d1, 0xfe05, 0x11d0,
                                     {0x9d, 0xda, 0x00, 0xc0, 0x4f, 0xd7, 0xba, 0x7c}};
static ULONG tracked[512];
static size_t count;
static size_t switches, ready_events;
static LONGLONG first_tick, last_tick;

static int keep(ULONG tid) {
    if (!tid) return 0;
    for (size_t i = 0; i < count; i++) if (tracked[i] == tid) return 1;
    return 0;
}

static ULONG read_u32(const unsigned char *p) {
    ULONG v;
    memcpy(&v, p, sizeof(v));
    return v;
}

static void WINAPI record(PEVENT_RECORD event) {
    if (memcmp(&event->EventHeader.ProviderId, &thread_provider, sizeof(GUID))) return;
    const unsigned char *p = event->UserData;
    LONGLONG ticks = event->EventHeader.TimeStamp.QuadPart;
    unsigned opcode = event->EventHeader.EventDescriptor.Opcode;
    if (opcode != 36 && opcode != 50) return;
    if (!first_tick || ticks < first_tick) first_tick = ticks;
    if (ticks > last_tick) last_tick = ticks;
    unsigned cpu = event->BufferContext.ProcessorNumber;
    switch (opcode) {
    case 36:
        if (event->UserDataLength < 16) return;
        ++switches;
        ULONG next = read_u32(p), previous = read_u32(p + 4);
        if (keep(previous))
            printf("%lld,O,%lu,%u,%u,%u\n", (long long)ticks, previous, cpu, p[14], p[12]);
        if (keep(next))
            printf("%lld,I,%lu,%u,0,0\n", (long long)ticks, next, cpu);
        break;
    case 50:
        if (event->UserDataLength < 4) return;
        ++ready_events;
        ULONG target = read_u32(p);
        ULONG waker = event->EventHeader.ThreadId;
        if (keep(target))
            printf("%lld,R,%lu,%u,%lu,0\n", (long long)ticks, target, cpu, keep(waker) ? waker : 0);
        break;
    }
}

int wmain(int argc, wchar_t **argv) {
    if (argc != 3) {
        fwprintf(stderr, L"Usage: scheduler-read TRACE.etl TIDS.txt\n");
        return 2;
    }
    FILE *f = _wfopen(argv[2], L"r");
    if (!f) return 2;
    ULONG tid;
    int parsed;
    while ((parsed = fscanf(f, "%lu", &tid)) == 1) {
        if (!tid || count == sizeof(tracked) / sizeof(tracked[0])) return 2;
        if (!keep(tid)) tracked[count++] = tid;
    }
    int errors = ferror(f);
    fclose(f);
    if (parsed != EOF || errors || !count) return 2;
    EVENT_TRACE_LOGFILEW logfile = {0};
    logfile.LogFileName = argv[1];
    logfile.ProcessTraceMode = PROCESS_TRACE_MODE_EVENT_RECORD | PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    logfile.EventRecordCallback = record;
    TRACEHANDLE handle = OpenTraceW(&logfile);
    if (handle == INVALID_PROCESSTRACE_HANDLE) {
        fprintf(stderr, "OpenTrace: %lu\n", (unsigned long)GetLastError());
        return 1;
    }
    printf("FREQ,%lld\n", (long long)logfile.LogfileHeader.PerfFreq.QuadPart);
    ULONG rc = ProcessTrace(&handle, 1, NULL, NULL);
    CloseTrace(handle);
    fprintf(stderr, "Scheduler events: CSwitch=%zu ReadyThread=%zu header_lost=%lu status=%lu\n",
            switches, ready_events, (unsigned long)logfile.LogfileHeader.EventsLost, (unsigned long)rc);
    fprintf(stderr, "Scheduler extent: first=%lld last=%lld\n", (long long)first_tick, (long long)last_tick);
    printf("EXTENT,%lld,%lld,%lu\n", (long long)first_tick, (long long)last_tick,
           (unsigned long)logfile.LogfileHeader.EventsLost);
    return rc != ERROR_SUCCESS || !switches || !ready_events || logfile.LogfileHeader.EventsLost;
}
