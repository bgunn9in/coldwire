CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror
CPPFLAGS += $(shell pkg-config --cflags libnetfilter_queue openssl)
LDLIBS += $(shell pkg-config --libs libnetfilter_queue openssl)

prefilter: prefilter.c

prefilter-batch: prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -DPREFILTER_BATCH $< -o $@ $(LDLIBS)

test-batch: test_batch.c prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDLIBS)

check: prefilter
	python3 test_prefilter.py

check-batch: prefilter-batch test-batch
	PREFILTER_BINARY="$(CURDIR)/prefilter-batch" python3 test_batch.py

.PHONY: check check-batch
