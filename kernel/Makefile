BUILD ?= /tmp/qlean-build
HOST_CC ?= cc
RV_CC ?= clang
RV_TARGET ?= --target=riscv32-unknown-elf
RV_LD ?= riscv64-unknown-elf-ld

CORE := src/arena.c src/parse.c src/elab.c src/check.c src/diagnostic.c
HOST := $(BUILD)/qlean-host
ELF := $(BUILD)/qlean.elf
COMMON := -std=c11 -Wall -Wextra -Wconversion -Werror -Iinclude
RV_ARCH := $(RV_TARGET) -march=rv32im -mabi=ilp32 -mno-relax -msmall-data-limit=0
RV_FLAGS := -Os -fno-builtin -ffreestanding -fno-pic -fno-stack-protector \
            -fno-unwind-tables -fno-asynchronous-unwind-tables -fno-jump-tables -fstack-usage
RV_SRC := $(CORE) rv32/io.c rv32/memory.c
RV_OBJS := $(patsubst %.c,$(BUILD)/%.o,$(RV_SRC)) $(BUILD)/rv32/start.o
HEADERS := src/internal.h include/qlean.h src/lean_keywords.inc

.PHONY: all host rv32 sanitize
all: host rv32
host: $(HOST)
rv32: $(ELF)

$(HOST): $(CORE) host/main.c $(HEADERS) Makefile
	mkdir -p $(@D)
	$(HOST_CC) $(COMMON) -O2 $(HOST_FLAGS) $(CORE) host/main.c -o $@

sanitize:
	$(MAKE) host BUILD="$(BUILD)/sanitize" HOST_CC=clang \
		HOST_FLAGS="-O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"

$(BUILD)/%.o: %.c $(HEADERS) Makefile
	mkdir -p $(@D)
	$(RV_CC) $(COMMON) $(RV_ARCH) $(RV_FLAGS) $(RV_EXTRA) -c $< -o $@

$(BUILD)/rv32/start.o: rv32/start.S
	mkdir -p $(@D)
	$(RV_CC) $(RV_ARCH) -c $< -o $@

$(ELF): $(RV_OBJS) rv32/qwenputer.ld
	$(RV_LD) -m elf32lriscv -static --no-relax --no-undefined \
		-Map $(BUILD)/qlean.map -T rv32/qwenputer.ld $(RV_OBJS) -o $@

.PHONY: sanitize-run
sanitize-run: sanitize
	mkdir -p $(BUILD)/sanitize
	clang $(COMMON) -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
		-fno-omit-frame-pointer $(CORE) ../tests/sanitize.c -o $(BUILD)/sanitize/fuzz
	$(BUILD)/sanitize/fuzz
