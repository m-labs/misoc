TARGET_PREFIX=$(TRIPLE)-

RM ?= rm -rf
PYTHON ?= python3

CARGO_TRIPLE=$(subst or1k-linux,or1k-unknown-none,$(TRIPLE))

ifeq ($(CLANG),1)
CC_normal      := clang -target $(TRIPLE) -integrated-as
CX_normal      := clang++ -target $(TRIPLE) -integrated-as
else
CC_normal      := $(TARGET_PREFIX)gcc -std=gnu99
CX_normal      := $(TARGET_PREFIX)g++
endif
AR_normal      := $(TARGET_PREFIX)ar
LD_normal      := $(TARGET_PREFIX)ld
OBJCOPY_normal := $(TARGET_PREFIX)objcopy
MSCIMG_normal  := $(PYTHON) -m misoc.tools.mkmscimg
CARGO_normal   := env CARGO_TARGET_DIR=$(realpath .)/cargo cargo rustc --target $(CARGO_TRIPLE)

CC_quiet      = @echo " CC      " $@ && $(CC_normal)
CX_quiet      = @echo " CX      " $@ && $(CX_normal)
AR_quiet      = @echo " AR      " $@ && $(AR_normal)
LD_quiet      = @echo " LD      " $@ && $(LD_normal)
OBJCOPY_quiet = @echo " OBJCOPY " $@ && $(OBJCOPY_normal)
MSCIMG_quiet  = @echo " MSCIMG  " $@ && $(MSCIMG_normal)
CARGO_quiet   = @echo " CARGO   " $@ && $(CARGO_normal)

ifeq ($(V),1)
	CC = $(CC_normal)
	CX = $(CX_normal)
	AR = $(AR_normal)
	LD = $(LD_normal)
	OBJCOPY = $(OBJCOPY_normal)
	MSCIMG = $(MSCIMG_normal)
	CARGO = $(CARGO_normal) --verbose
else
	CC = $(CC_quiet)
	CX = $(CX_quiet)
	AR = $(AR_quiet)
	LD = $(LD_quiet)
	OBJCOPY = $(OBJCOPY_quiet)
	MSCIMG = $(MSCIMG_quiet)
	CARGO = $(CARGO_quiet)
.SILENT:
endif

# C toolchain options
INCLUDES = -I$(MISOC_DIRECTORY)/software/include/base -I$(MISOC_DIRECTORY)/software/include -I$(MISOC_DIRECTORY)/common -I$(BUILDINC_DIRECTORY)
COMMONFLAGS = -Os $(CPUFLAGS) -fomit-frame-pointer -ffunction-sections -Wall -fno-builtin -nostdinc $(INCLUDES)
ifeq ($(CPU),vexriscv)
	COMMONFLAGS += -mcmodel=medany
endif
CFLAGS = $(COMMONFLAGS) -fexceptions -Wstrict-prototypes -Wold-style-definition -Wmissing-prototypes -Werror=incompatible-pointer-types
CXXFLAGS = $(COMMONFLAGS) -std=c++11 -I$(MISOC_DIRECTORY)/software/include/basec++ -fexceptions -fno-rtti -ffreestanding


# Rust toolchain options
RUSTOUT = cargo/$(CARGO_TRIPLE)/debug
export RUSTFLAGS = -Ctarget-feature=+mul,+div,+ffl1,+cmov,+addc -Crelocation-model=static -Copt-level=s
export CC_$(subst -,_,$(CARGO_TRIPLE)) = clang
export CFLAGS_$(subst -,_,$(CARGO_TRIPLE)) = $(CFLAGS)

# Linker options
LDFLAGS = --gc-sections -nostdlib -nodefaultlibs -L$(BUILDINC_DIRECTORY)

ifeq ($(CPU),vexriscv)
	CPU_ENDIANNESS = LITTLE
else
	CPU_ENDIANNESS = BIG
endif

define assemble
$(CC) -c $(CFLAGS) -o $@ $<
endef

define compile
$(CC) -c $(CFLAGS) $< -o $@
endef

define compilexx
$(CX) -c $(CXXFLAGS) $< -o $@
endef

define archive
$(AR) crs $@ $^
endef

define link
$(LD) $(LDFLAGS) $^ -o $@
endef

define objcopy
$(OBJCOPY) $< $@
endef

define mscimg
$(MSCIMG) -f -o $@ $<
endef

define cargo
$(CARGO)
endef

define clean
$(RM) cargo/ *.bin *.elf *.fbi *.a *.o $(1)
endef

.PHONY: all
all::

.PHONY: clean
clean:
	$(clean)
