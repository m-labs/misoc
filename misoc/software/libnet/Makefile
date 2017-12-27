include ../include/generated/variables.mak
include $(MISOC_DIRECTORY)/software/common.mak

all:: libnet.a

libnet.a: microudp.o tftp.o
	$(archive)

%.o: $(LIBNET_DIRECTORY)/%.c
	$(compile)
