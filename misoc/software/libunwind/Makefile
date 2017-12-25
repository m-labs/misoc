include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

# lm32 is not supported
ifeq ($(CPU),lm32)
	ALL_TARGET=
else
	ALL_TARGET=libunwind-bare.a libunwind-elf.a
endif

COMMONFLAGS += -integrated-as -I. \
	-I$(MISOC_DIRECTORY)/software/include/dyld/ \
	-I$(MISOC_DIRECTORY)/software/unwinder/include/ \
	-I$(LIBUNWIND_DIRECTORY) \
	-D__ELF__ -D__linux__ \
	-D_LIBUNWIND_NO_HEAP -D_LIBUNWIND_BUILD_ZERO_COST_APIS \
	-DNDEBUG

OBJECTS = UnwindRegistersSave.o UnwindRegistersRestore.o

.PHONY: all
all: $(ALL_TARGET)

libunwind-%.a: $(OBJECTS) UnwindLevel1-%.o UnwindLevel1-gcc-ext-%.o libunwind-%.o
	$(archive)

%-elf.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx)

%-elf.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile)

%-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx) -D_LIBUNWIND_IS_BAREMETAL

%-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile) -D_LIBUNWIND_IS_BAREMETAL

%.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.S
	$(assemble)

.PHONY: clean
clean:
	$(clean)
