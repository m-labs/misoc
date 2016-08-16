#include <generated/csr.h>
#include <stdio.h>
#include <stdarg.h>

void isr(void);

#ifdef __or1k__

#define EXTERNAL_IRQ 0x8

static void emerg_printf(const char *fmt, ...)
{
	char buf[128];
	va_list args;
	va_start(args, fmt);
	vsnprintf(buf, sizeof(buf), fmt, args);
	va_end(args);

	char *p = buf;
	while(*p) {
		while(uart_txfull_read());
		uart_rxtx_write(*p++);
	}
}

void exception_handler(unsigned long vect, unsigned long *regs,
                       unsigned long pc, unsigned long ea);
void exception_handler(unsigned long vect, unsigned long *regs,
                       unsigned long pc, unsigned long ea)
{
	if(vect == EXTERNAL_IRQ) {
		isr();
	} else {
		emerg_printf("\n *** Unhandled exception %d *** \n", vect);
		emerg_printf("   pc  %08x ea  %08x\n",
		             pc, ea);
		unsigned long r1 = (unsigned long)regs + 4*32;
		regs -= 2;
		emerg_printf("   r0  %08x r1  %08x r2  %08x r3  %08x\n",
		             0, r1, regs[2], regs[3]);
		emerg_printf("   r4  %08x r5  %08x r6  %08x r7  %08x\n",
		             regs[4], regs[5], regs[6], regs[7]);
		emerg_printf("   r8  %08x r9  %08x r10 %08x r11 %08x\n",
		             regs[8], regs[9], regs[10], regs[11]);
		emerg_printf("   r12 %08x r13 %08x r14 %08x r15 %08x\n",
		             regs[12], regs[13], regs[14], regs[15]);
		emerg_printf("   r16 %08x r17 %08x r18 %08x r19 %08x\n",
		             regs[16], regs[17], regs[18], regs[19]);
		emerg_printf("   r20 %08x r21 %08x r22 %08x r23 %08x\n",
		             regs[20], regs[21], regs[22], regs[23]);
		emerg_printf("   r24 %08x r25 %08x r26 %08x r27 %08x\n",
		             regs[24], regs[25], regs[26], regs[27]);
		emerg_printf("   r28 %08x r29 %08x r30 %08x r31 %08x\n",
		             regs[28], regs[29], regs[30], regs[31]);
		emerg_printf(" stack:\n");
		unsigned long *sp = (unsigned long *)r1;
		for(unsigned long spoff = 0; spoff < 16; spoff += 4) {
			emerg_printf("   %08x:", &sp[spoff]);
			for(unsigned long spoff2 = 0; spoff2 < 4; spoff2++) {
				emerg_printf(" %08x", sp[spoff + spoff2]);
			}
			emerg_printf("\n");
		}
		for(;;);
	}
}
#endif
