include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

COMMONFLAGS += -integrated-as -I. \
	-I$(MISOC_DIRECTORY)/software/include/dyld/ \
	-I$(MISOC_DIRECTORY)/software/unwinder/include/ \
	-I$(LIBUNWIND_DIRECTORY) \
	-D__ELF__ -D__linux__ \
	-D_LIBUNWIND_NO_HEAP -D_LIBUNWIND_BUILD_ZERO_COST_APIS \
	-DNDEBUG

ifeq ($(CPU),or1k)
all:: libunwind-bare.a libunwind-elf.a
endif

libunwind-%.a: UnwindRegistersSave.o UnwindRegistersRestore.o \
		UnwindLevel1-%.o UnwindLevel1-gcc-ext-%.o libunwind-%.o
	$(archive)

%.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.S
	$(assemble)

%-elf.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx)

%-elf.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile)

%-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx) -D_LIBUNWIND_IS_BAREMETAL

%-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile) -D_LIBUNWIND_IS_BAREMETAL
