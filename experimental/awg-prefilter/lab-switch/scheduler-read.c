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
static const GUID stack_provider = {0xdef2fe46, 0x7bd6, 0x4b80,
                                    {0xbd, 0x94, 0xf5, 0x7f, 0xe2, 0x0d, 0x0c, 0xe3}};
static size_t stack_events, selected_stacks;
static int details;
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

static const GUID image_provider = {0x2cb15d1d, 0x5fc1, 0x11d2,
                                    {0xab, 0xe1, 0x00, 0xa0, 0xc9, 0x11, 0xf5, 0x18}};
static unsigned long long read_pointer(const unsigned char *p, size_t width) {
    unsigned long long address = 0;
    memcpy(&address, p, width);
    return address;
}
static const GUID fault_provider = {0x3d6fa8d3, 0xfe05, 0x11d0,
                                    {0x9d, 0xda, 0x00, 0xc0, 0x4f, 0xd7, 0xba, 0x7c}};
static const GUID disk_provider = {0x3d6fa8d4, 0xfe05, 0x11d0,
                                   {0x9d, 0xda, 0x00, 0xc0, 0x4f, 0xd7, 0xba, 0x7c}};

static void record_details(PEVENT_RECORD event) {
    const unsigned char *body = event->UserData;
    unsigned opcode_all = event->EventHeader.EventDescriptor.Opcode;
    size_t width_all = (event->EventHeader.Flags & EVENT_HEADER_FLAG_32_BIT_HEADER) ? 4 : 8;
    size_t body_len = event->UserDataLength;
    unsigned long long stamp = event->EventHeader.TimeStamp.QuadPart;
    if (!memcmp(&event->EventHeader.ProviderId, &fault_provider, sizeof(GUID))) {
        if (opcode_all == 32 && body_len >= 16 + width_all * 2 + 8) {
            ULONG tid = read_u32(body + 16 + width_all * 2);
            if (keep(tid))
                printf("%llu,H,%lu,%llu,%llx,%llx,%lu\n", stamp, tid,
                       read_pointer(body, 8), read_pointer(body + 16, width_all),
                       read_pointer(body + 16 + width_all, width_all),
                       read_u32(body + 20 + width_all * 2));
        }
        return;
    }
    if (!memcmp(&event->EventHeader.ProviderId, &disk_provider, sizeof(GUID))) {
        if ((opcode_all == 10 || opcode_all == 11) && body_len >= 36 + width_all * 2) {
            ULONG tid = read_u32(body + 32 + width_all * 2);
            if (keep(tid))
                printf("%llu,D,%lu,%u,%llu,%lu,%lu,%llx\n", stamp, tid, opcode_all,
                       read_pointer(body + 24 + width_all * 2, 8),
                       read_u32(body), read_u32(body + 8), read_pointer(body + 24, width_all));
        }
        return;
    }
    if (!memcmp(&event->EventHeader.ProviderId, &image_provider, sizeof(GUID))) {
        if (event->EventHeader.EventDescriptor.Version < 2) return;
        size_t name_at = width_all * 3 + 32;
        if (body_len < name_at + 2) return;
        const wchar_t *name = (const wchar_t *)(body + name_at);
        size_t limit = (body_len - name_at) / sizeof(*name);
        size_t length = 0, basename = 0;
        while (length < limit && name[length]) {
            if (name[length] == L'\\' || name[length] == L'/') basename = length + 1;
            ++length;
        }
        if (length == limit || length == basename) return;
        char utf8[MAX_PATH * 3];
        int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, name + basename,
                                        (int)(length - basename), utf8, sizeof(utf8), NULL, NULL);
        if (!bytes) return;
        printf("IMAGE,%llx,%llx,\"%.*s\",%lu\n", read_pointer(body, width_all),
               read_pointer(body + width_all, width_all), bytes, utf8,
               read_u32(body + 2 * width_all));
        return;
    }
    if (!memcmp(&event->EventHeader.ProviderId, &stack_provider, sizeof(GUID))) {
        if (event->EventHeader.EventDescriptor.Opcode != 32 ||
            event->UserDataLength < 16) return;
        ++stack_events;
        const unsigned char *data = event->UserData;
        ULONG tid = read_u32(data + 12);
        if (!keep(tid)) return;
        ++selected_stacks;
        printf("%llu,S,%lu,%lu", read_pointer(data, 8), tid, read_u32(data + 8));
        for (size_t offset = 16; offset + width_all <= body_len; offset += width_all) {
            printf(",%llx", read_pointer(data + offset, width_all));
        }
        puts("");
        return;
    }
}

static void WINAPI record(PEVENT_RECORD event) {
    if (memcmp(&event->EventHeader.ProviderId, &thread_provider, sizeof(GUID))) {
        if (details) record_details(event);
        return;
    }
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
    details = argc == 4 && !wcscmp(argv[3], L"--details");
    if (argc != 3 && !details) {
        fwprintf(stderr, L"Usage: scheduler-read TRACE.etl TIDS.txt [--details]\n");
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
    if (details)
        fprintf(stderr, "StackWalk=%zu selected=%zu\n", stack_events, selected_stacks);
    printf("EXTENT,%lld,%lld,%lu\n", (long long)first_tick, (long long)last_tick,
           (unsigned long)logfile.LogfileHeader.EventsLost);
    return rc != ERROR_SUCCESS || !switches || !ready_events || logfile.LogfileHeader.EventsLost ||
           (details && !selected_stacks);
}
