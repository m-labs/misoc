include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

COMMONFLAGS += -I$(MISOC_DIRECTORY)/software/include/dyld

# lm32 is not supported
ifeq ($(CPU),or1k)
all:: libdyld.a
endif

libdyld.a: dyld.o
	$(archive)

%.o: $(LIBDYLD_DIRECTORY)/%.c
	$(compile)
