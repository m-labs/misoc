include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

OBJECTS = microudp.o tftp.o

.PHONY: all
all: libnet.a

libnet.a: $(OBJECTS)
	$(archive)

%.o: $(LIBNET_DIRECTORY)/%.c
	$(compile)

.PHONY: clean
clean:
	$(clean)
