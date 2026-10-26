# Standalone Compás early-splash build. Player and shared bootloader sources
# are consumed from the public compas-player checkout.

.DEFAULT_GOAL := early-splash

BOARD ?= r1
VALID_BOARDS := r1 r3proii r3ii_2025
ifeq ($(filter $(BOARD),$(VALID_BOARDS)),)
$(error Unknown BOARD '$(BOARD)' -- expected r1, r3proii, or r3ii_2025)
endif

COMPAS_PLAYER_DIR ?= $(abspath $(CURDIR)/../compas-player)
PLAYER_DIR := $(abspath $(COMPAS_PLAYER_DIR))
CROSS_CC ?= mipsel-linux-musl-gcc
CROSS_STRIP ?= mipsel-linux-musl-strip
TARGET_CPU_FLAGS ?= -march=mips32r2 -mabi=32 -mfp32 -mno-odd-spreg -ffp-contract=off
BOARD_DEFINE := -DBOARD_$(shell echo $(BOARD) | tr a-z A-Z)

ifeq ($(BOARD),r1)
EARLY_SPLASH_BIN := build/compas_early_splash
else
EARLY_SPLASH_BIN := build/compas_early_splash_$(BOARD)
endif

PRIVATE_EARLY_SPLASH := src/bootloader/startup/early_splash.c
PLAYER_EARLY_SPLASH_SRCS := \
	$(PLAYER_DIR)/src/bootloader/display/fb_draw.c \
	$(PLAYER_DIR)/src/bootloader/install/internal_storage.c \
	$(PLAYER_DIR)/src/core/ui/display/startup_splash.c \
	$(PLAYER_DIR)/src/core/ui/web/glyph5x7.c \
	$(PLAYER_DIR)/lvgl/src/libs/tjpgd/tjpgd.c
EARLY_SPLASH_SRCS := $(PRIVATE_EARLY_SPLASH) $(PLAYER_EARLY_SPLASH_SRCS)
BOOTLOADER_CFLAGS := -O2 -Wall -I$(PLAYER_DIR) -I$(PLAYER_DIR)/src/bootloader \
	-I$(PLAYER_DIR)/src/core -I$(PLAYER_DIR)/src/bootloader/startup \
	-DCOMPAS_LOADER_BUILD $(BOARD_DEFINE) -ffunction-sections -fdata-sections

.PHONY: all early-splash clean FORCE prepare-player
all: early-splash
early-splash: $(EARLY_SPLASH_BIN)
FORCE:
prepare-player:
	$(MAKE) -C "$(PLAYER_DIR)" BOARD="$(BOARD)" lvgl/.lvgl_fbdev_patch_applied

$(EARLY_SPLASH_BIN): FORCE $(PRIVATE_EARLY_SPLASH) Makefile | prepare-player
	@mkdir -p $(dir $@)
	@set -e; tmp="$@.tmp"; stripped="$@.strip.tmp"; \
	  trap 'rm -f "$$tmp" "$$stripped"' EXIT; \
	  $(CROSS_CC) $(TARGET_CPU_FLAGS) $(BOOTLOADER_CFLAGS) -static -no-pie \
	    $(EARLY_SPLASH_SRCS) -Wl,--gc-sections -lm -o "$$tmp"; \
	  $(CROSS_STRIP) -s -o "$$stripped" "$$tmp"; \
	  chmod 0755 "$$stripped"; mv -f "$$stripped" "$@"
	@echo "Standalone Compás early splash ready: $@"

clean:
	rm -f build/compas_early_splash build/compas_early_splash_*
