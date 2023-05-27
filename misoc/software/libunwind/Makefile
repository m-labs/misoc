include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

COMMONFLAGS += -integrated-as -I. \
	-I$(MISOC_DIRECTORY)/software/include/dyld/ \
	-I$(MISOC_DIRECTORY)/software/unwinder/include/ \
	-I$(LIBUNWIND_DIRECTORY) \
	-D__ELF__ -D__linux__ \
	-D_LIBUNWIND_NO_HEAP -DNDEBUG

ifeq ($(CPU),or1k)
COMMONFLAGS += -D_LIBUNWIND_BUILD_ZERO_COST_APIS
endif

CFLAGS += -funwind-tables
CXXFLAGS += -fno-exceptions -funwind-tables


all:: libunwind-$(CPU)-bare.a libunwind-$(CPU)-libc.a

libunwind-$(CPU)-%.a: UnwindRegistersSave-$(CPU)-%.o UnwindRegistersRestore-$(CPU)-%.o \
		UnwindLevel1-$(CPU)-%.o UnwindLevel1-gcc-ext-$(CPU)-%.o libunwind-$(CPU)-%.o
	$(archive)


%-$(CPU)-libc.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.S
	$(assemble)

%-$(CPU)-libc.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile)


%-$(CPU)-libc.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx)


%-$(CPU)-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.S
	$(assemble)

%-$(CPU)-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.c
	$(compile) -D_LIBUNWIND_IS_BAREMETAL

%-$(CPU)-bare.o: $(MISOC_DIRECTORY)/software/unwinder/src/%.cpp
	$(compilexx) -D_LIBUNWIND_IS_BAREMETAL
