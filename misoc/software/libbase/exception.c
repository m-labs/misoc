#include <generated/csr.h>
#include <stdio.h>

void isr(void);

#ifdef __or1k__

#define EXTERNAL_IRQ 0x8

void exception_handler(unsigned long vect, unsigned long *regs,
                       unsigned long pc, unsigned long ea);
void exception_handler(unsigned long vect, unsigned long *regs,
                       unsigned long pc, unsigned long ea)
{
	if(vect == EXTERNAL_IRQ) {
		isr();
	} else {
		char outbuf[128];
		scnprintf(outbuf, sizeof(outbuf),
		          "\n *** Unhandled exception %d at PC 0x%08x, EA 0x%08x *** \n",
		          vect, pc, ea);

		char *p = outbuf;
		while(*p) {
			while(uart_txfull_read());
			uart_rxtx_write(*p++);
		}

		for(;;);
	}
}
#endif
