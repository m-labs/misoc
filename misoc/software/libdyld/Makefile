include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

# lm32 is not supported
ifeq ($(CPU),lm32)
	ALL_TARGET=
else
	ALL_TARGET=libdyld.a
endif

COMMONFLAGS += -I$(MISOC_DIRECTORY)/software/include/dyld

OBJECTS = dyld.o

.PHONY: all
all: $(ALL_TARGET)

libdyld.a: $(OBJECTS)
	$(archive)

%.o: $(LIBDYLD_DIRECTORY)/%.c
	$(compile)

.PHONY: clean
clean:
	$(clean)
