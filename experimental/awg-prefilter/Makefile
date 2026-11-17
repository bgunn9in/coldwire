CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror
CPPFLAGS += $(shell pkg-config --cflags libnetfilter_queue openssl)
LDLIBS += $(shell pkg-config --libs libnetfilter_queue openssl)

prefilter: prefilter.c

prefilter-batch: prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -DPREFILTER_BATCH $< -o $@ $(LDLIBS)

test-batch: test_batch.c prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDLIBS)

test-netlink: test_netlink.c prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $< -o $@ $(LDLIBS)

check: prefilter test-netlink
	./test-netlink
	python3 test_prefilter.py

check-batch: prefilter-batch test-batch
	PREFILTER_BINARY="$(CURDIR)/prefilter-batch" python3 test_batch.py

prefilter-handshake: prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -DPREFILTER_BATCH -DPREFILTER_HANDSHAKE_MARK $< -o $@ $(LDLIBS)

test-batch-handshake: test_batch.c prefilter.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -DPREFILTER_HANDSHAKE_MARK $< -o $@ $(LDLIBS)

check-handshake: prefilter-handshake test-batch-handshake
	PREFILTER_BINARY="$(CURDIR)/prefilter-handshake" python3 test_prefilter.py
	PREFILTER_BATCH_DRIVER="$(CURDIR)/test-batch-handshake" python3 test_handshake_mark.py

flow-confirmation/escrow: flow-confirmation/escrow.c

check-escrow: flow-confirmation/escrow
	./flow-confirmation/escrow --self-test
	python3 flow-confirmation/test_agent.py
	python3 flow-confirmation/test_conntrack.py

lab-switch/noise-multi-source: lab-switch/noise-multi-source.c
	$(CC) $(CFLAGS) $< -o $@

lab-switch/udp-load: lab-switch/udp-load.c
	$(CC) $(CFLAGS) $< -o $@

check-lab-tools: lab-switch/noise-multi-source lab-switch/udp-load
	./lab-switch/udp-load --self-test
	./lab-switch/noise-multi-source --self-test
	python3 lab-switch/udp-capture.py --self-test

.PHONY: check check-batch check-handshake check-escrow check-lab-tools
