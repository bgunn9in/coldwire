CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror
CPPFLAGS += $(shell pkg-config --cflags libnetfilter_queue openssl)
LDLIBS += $(shell pkg-config --libs libnetfilter_queue openssl)

prefilter: prefilter.c

check: prefilter
	python3 test_prefilter.py

.PHONY: check
