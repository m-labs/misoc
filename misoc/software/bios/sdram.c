#include <generated/csr.h>
#ifdef CSR_DFII_BASE

#include <stdio.h>
#include <stdlib.h>

#include <generated/sdram_phy.h>
#include <generated/mem.h>
#include <hw/flags.h>
#include <system.h>

#include "sdram.h"

static void cdelay(int i)
{
	while(i > 0) {
#if defined (__lm32__)
		__asm__ volatile("nop");
#elif defined (__or1k__)
		__asm__ volatile("l.nop");
#elif defined (__vexriscv__)
		__asm__ volatile("nop");
#else
#error Unsupported architecture
#endif
		i--;
	}
}

void sdrsw(void)
{
	dfii_control_write(DFII_CONTROL_CKE|DFII_CONTROL_ODT|DFII_CONTROL_RESET_N);
	printf("SDRAM now under software control\n");
}

void sdrhw(void)
{
	dfii_control_write(DFII_CONTROL_SEL);
	printf("SDRAM now under hardware control\n");
}

void sdrrow(char *_row)
{
	char *c;
	unsigned int row;

	if(*_row == 0) {
		dfii_pi0_address_write(0x0000);
		dfii_pi0_baddress_write(0);
		command_p0(DFII_COMMAND_RAS|DFII_COMMAND_WE|DFII_COMMAND_CS);
		cdelay(15);
		printf("Precharged\n");
	} else {
		row = strtoul(_row, &c, 0);
		if(*c != 0) {
			printf("incorrect row\n");
			return;
		}
		dfii_pi0_address_write(row);
		dfii_pi0_baddress_write(0);
		command_p0(DFII_COMMAND_RAS|DFII_COMMAND_CS);
		cdelay(15);
		printf("Activated row %d\n", row);
	}
}

void sdrrdbuf(int dq)
{
	int i, p;
	int first_byte, step;

	if(dq < 0) {
		first_byte = 0;
		step = 1;
	} else {
		first_byte = DFII_PIX_DATA_SIZE/2 - 1 - dq;
		step = DFII_PIX_DATA_SIZE/2;
	}

	for(p=0;p<DFII_NPHASES;p++)
		for(i=first_byte;i<DFII_PIX_DATA_SIZE;i+=step)
			printf("%02x", MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i));
	printf("\n");
}

void sdrrd(char *startaddr, char *dq)
{
	char *c;
	unsigned int addr;
	int _dq;

	if(*startaddr == 0) {
		printf("sdrrd <address>\n");
		return;
	}
	addr = strtoul(startaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}
	if(*dq == 0)
		_dq = -1;
	else {
		_dq = strtoul(dq, &c, 0);
		if(*c != 0) {
			printf("incorrect DQ\n");
			return;
		}
	}

	dfii_pird_address_write(addr);
	dfii_pird_baddress_write(0);
	command_prd(DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA);
	cdelay(15);
	sdrrdbuf(_dq);
}

void sdrrderr(char *count)
{
	int addr;
	char *c;
	int _count;
	int i, j, p;
	unsigned char prev_data[DFII_NPHASES*DFII_PIX_DATA_SIZE];
	unsigned char errs[DFII_NPHASES*DFII_PIX_DATA_SIZE];

	if(*count == 0) {
		printf("sdrrderr <count>\n");
		return;
	}
	_count = strtoul(count, &c, 0);
	if(*c != 0) {
		printf("incorrect count\n");
		return;
	}

	for(i=0;i<DFII_NPHASES*DFII_PIX_DATA_SIZE;i++)
			errs[i] = 0;
	for(addr=0;addr<16;addr++) {
		dfii_pird_address_write(addr*8);
		dfii_pird_baddress_write(0);
		command_prd(DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA);
		cdelay(15);
		for(p=0;p<DFII_NPHASES;p++)
			for(i=0;i<DFII_PIX_DATA_SIZE;i++)
				prev_data[p*DFII_PIX_DATA_SIZE+i] = MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i);

		for(j=0;j<_count;j++) {
			command_prd(DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA);
			cdelay(15);
			for(p=0;p<DFII_NPHASES;p++)
				for(i=0;i<DFII_PIX_DATA_SIZE;i++) {
					unsigned char new_data;

					new_data = MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i);
					errs[p*DFII_PIX_DATA_SIZE+i] |= prev_data[p*DFII_PIX_DATA_SIZE+i] ^ new_data;
					prev_data[p*DFII_PIX_DATA_SIZE+i] = new_data;
				}
		}
	}

	for(i=0;i<DFII_NPHASES*DFII_PIX_DATA_SIZE;i++)
		printf("%02x", errs[i]);
	printf("\n");
	for(p=0;p<DFII_NPHASES;p++)
		for(i=0;i<DFII_PIX_DATA_SIZE;i++)
			printf("%2x", DFII_PIX_DATA_SIZE/2 - 1 - (i % (DFII_PIX_DATA_SIZE/2)));
	printf("\n");
}

void sdrwr(char *startaddr)
{
	char *c;
	unsigned int addr;
	int i;
	int p;

	if(*startaddr == 0) {
		printf("sdrrd <address>\n");
		return;
	}
	addr = strtoul(startaddr, &c, 0);
	if(*c != 0) {
		printf("incorrect address\n");
		return;
	}

	for(p=0;p<DFII_NPHASES;p++)
		for(i=0;i<DFII_PIX_DATA_SIZE;i++)
			MMPTR(dfii_pix_wrdata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i) = 0x10*p + i;

	dfii_piwr_address_write(addr);
	dfii_piwr_baddress_write(0);
	command_pwr(DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS|DFII_COMMAND_WRDATA);
}

#ifdef CSR_DDRPHY_BASE

#ifdef CONFIG_KUSDDRPHY
#define ERR_DDRPHY_DELAY 512
#else
#define ERR_DDRPHY_DELAY 32
#endif

#ifdef CONFIG_DDRPHY_WLEVEL

void sdrwlon(void)
{
	dfii_pi0_address_write(DDR3_MR1 | (1 << 7));
	dfii_pi0_baddress_write(1);
	command_p0(DFII_COMMAND_RAS|DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS);
	ddrphy_wlevel_en_write(1);
}

void sdrwloff(void)
{
	dfii_pi0_address_write(DDR3_MR1);
	dfii_pi0_baddress_write(1);
	command_p0(DFII_COMMAND_RAS|DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS);
	ddrphy_wlevel_en_write(0);
}

static int write_level(int *delay, int *high_skew)
{
	int i;
	int dq_address;
	unsigned char dq;
	int ok;

	printf("Write leveling: ");

	sdrwlon();
	cdelay(100);
	for(i=0;i<DFII_PIX_DATA_SIZE/2;i++) {
		dq_address = dfii_pix_rddata_addr[0]+CONFIG_DATA_WIDTH_BYTES*(DFII_PIX_DATA_SIZE/2-1-i);
		ddrphy_dly_sel_write(1 << i);
		ddrphy_wdly_dq_rst_write(1);
		ddrphy_wdly_dqs_rst_write(1);

		delay[i] = 0;

		ddrphy_wlevel_strobe_write(1);
		cdelay(10);
		dq = MMPTR(dq_address);
		if(dq != 0) {
			/*
			 * Assume this DQ group has between 1 and 2 bit times of skew.
			 * Bring DQS into the CK=0 zone before continuing leveling.
			 */
			high_skew[i] = 1;
			while(dq != 0) {
				delay[i]++;
				if(delay[i] >= ERR_DDRPHY_DELAY)
					break;
				ddrphy_wdly_dq_inc_write(1);
				ddrphy_wdly_dqs_inc_write(1);
				ddrphy_wlevel_strobe_write(1);
				cdelay(10);
				dq = MMPTR(dq_address);
			 }
		} else
			high_skew[i] = 0;

		while(dq == 0) {
			delay[i]++;
			if(delay[i] >= ERR_DDRPHY_DELAY)
				break;
			ddrphy_wdly_dq_inc_write(1);
			ddrphy_wdly_dqs_inc_write(1);

			ddrphy_wlevel_strobe_write(1);
			cdelay(10);
			dq = MMPTR(dq_address);
		}
	}
	sdrwloff();

	ok = 1;
	for(i=DFII_PIX_DATA_SIZE/2-1;i>=0;i--) {
		printf("%2d%c ", delay[i], high_skew[i] ? '*' : ' ');
		if(delay[i] >= ERR_DDRPHY_DELAY)
			ok = 0;
	}

	if(ok)
		printf("completed\n");
	else
		printf("failed\n");

	return ok;
}

#endif /* CONFIG_DDRPHY_WLEVEL */

static void read_bitslip(int *delay, int *high_skew)
{
	int bitslip_thr;
	int i;

	bitslip_thr = 0x7fffffff;
	for(i=0;i<DFII_PIX_DATA_SIZE/2;i++)
		if(high_skew[i] && (delay[i] < bitslip_thr))
			bitslip_thr = delay[i];
	if(bitslip_thr == 0x7fffffff)
		return;
	bitslip_thr = bitslip_thr/2;

	printf("Read bitslip: ");
	for(i=DFII_PIX_DATA_SIZE/2-1;i>=0;i--)
		if(delay[i] > bitslip_thr) {
			ddrphy_dly_sel_write(1 << i);
#ifdef CONFIG_KUSDDRPHY
			ddrphy_rdly_dq_bitslip_write(1);
#else
			/* 7-series SERDES in DDR mode needs 3 pulses for 1 bitslip */
			ddrphy_rdly_dq_bitslip_write(1);
			ddrphy_rdly_dq_bitslip_write(1);
			ddrphy_rdly_dq_bitslip_write(1);
#endif
			printf("%d ", i);
		}
	printf("\n");
}

static void read_delays(void)
{
	unsigned int prv;
	unsigned char prs[DFII_NPHASES*DFII_PIX_DATA_SIZE];
	int p, i, j;
	int working;
	int delay, delay_min, delay_max;

	printf("Read delays: ");

	/* Generate pseudo-random sequence */
	prv = 42;
	for(i=0;i<DFII_NPHASES*DFII_PIX_DATA_SIZE;i++) {
		prv = 1664525*prv + 1013904223;
		prs[i] = prv;
	}

	/* Activate */
	dfii_pi0_address_write(0);
	dfii_pi0_baddress_write(0);
	command_p0(DFII_COMMAND_RAS|DFII_COMMAND_CS);
	cdelay(15);

	/* Write test pattern */
	for(p=0;p<DFII_NPHASES;p++)
		for(i=0;i<DFII_PIX_DATA_SIZE;i++)
			MMPTR(dfii_pix_wrdata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i) = prs[DFII_PIX_DATA_SIZE*p+i];
	dfii_piwr_address_write(0);
	dfii_piwr_baddress_write(0);
	command_pwr(DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS|DFII_COMMAND_WRDATA);

	/* Calibrate each DQ in turn */
	dfii_pird_address_write(0);
	dfii_pird_baddress_write(0);
	for(i=0;i<DFII_PIX_DATA_SIZE/2;i++) {
		ddrphy_dly_sel_write(1 << (DFII_PIX_DATA_SIZE/2-i-1));
		delay = 0;

		/* Find smallest working delay */
		ddrphy_rdly_dq_rst_write(1);
		while(1) {
			command_prd(DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA);
			cdelay(15);
			working = 1;
			for(p=0;p<DFII_NPHASES;p++) {
				if(MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i) != prs[DFII_PIX_DATA_SIZE*p+i])
					working = 0;
				if(MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*(i+DFII_PIX_DATA_SIZE/2)) != prs[DFII_PIX_DATA_SIZE*p+i+DFII_PIX_DATA_SIZE/2])
					working = 0;
			}
			if(working)
				break;
			delay++;
			if(delay >= ERR_DDRPHY_DELAY)
				break;
			ddrphy_rdly_dq_inc_write(1);
		}
		delay_min = delay;

		/* Get a bit further into the working zone */
#ifdef CONFIG_KUSDDRPHY
		for(j=0;j<16;j++) {
			delay += 1;
			ddrphy_rdly_dq_inc_write(1);
		}
#else
		delay++;
		ddrphy_rdly_dq_inc_write(1);
#endif

		/* Find largest working delay */
		while(1) {
			command_prd(DFII_COMMAND_CAS|DFII_COMMAND_CS|DFII_COMMAND_RDDATA);
			cdelay(15);
			working = 1;
			for(p=0;p<DFII_NPHASES;p++) {
				if(MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*i) != prs[DFII_PIX_DATA_SIZE*p+i])
					working = 0;
				if(MMPTR(dfii_pix_rddata_addr[p]+CONFIG_DATA_WIDTH_BYTES*(i+DFII_PIX_DATA_SIZE/2)) != prs[DFII_PIX_DATA_SIZE*p+i+DFII_PIX_DATA_SIZE/2])
					working = 0;
			}
			if(!working)
				break;
			delay++;
			if(delay >= ERR_DDRPHY_DELAY)
				break;
			ddrphy_rdly_dq_inc_write(1);
		}
		delay_max = delay;

		printf("%d:%02d-%02d  ", DFII_PIX_DATA_SIZE/2-i-1, delay_min, delay_max);

		/* Set delay to the middle */
		ddrphy_rdly_dq_rst_write(1);
		for(j=0;j<(delay_min+delay_max)/2;j++)
			ddrphy_rdly_dq_inc_write(1);
	}

	/* Precharge */
	dfii_pi0_address_write(0);
	dfii_pi0_baddress_write(0);
	command_p0(DFII_COMMAND_RAS|DFII_COMMAND_WE|DFII_COMMAND_CS);
	cdelay(15);

	printf("completed\n");
}

int sdrlevel(void)
{
	int delay[DFII_PIX_DATA_SIZE/2];
	int high_skew[DFII_PIX_DATA_SIZE/2];

#ifndef CONFIG_DDRPHY_WLEVEL
	int i;
	for(i=0; i<DFII_PIX_DATA_SIZE/2; i++) {
		delay[i] = 0;
		high_skew[i] = 0;
	}
#else
	if(!write_level(delay, high_skew))
		return 0;
#endif
	read_bitslip(delay, high_skew);
	read_delays();

	return 1;
}

#endif /* CSR_DDRPHY_BASE */

#define TEST_DATA_SIZE (2*1024*1024)
#define TEST_DATA_RANDOM 1

#define TEST_ADDR_SIZE (32*1024)
#define TEST_ADDR_RANDOM 0

#define ONEZERO 0xAAAAAAAA
#define ZEROONE 0x55555555

static unsigned int seed_to_data_32(unsigned int seed, int random)
{
	if (random)
		return 1664525*seed + 1013904223;
	else
		return seed + 1;
}

static unsigned short seed_to_data_16(unsigned short seed, int random)
{
	if (random)
		return 25173*seed + 13849;
	else
		return seed + 1;
}

int memtest_silent(void)
{
	volatile unsigned int *array = (unsigned int *)MAIN_RAM_BASE;
	int i;
	unsigned int seed_32;
	unsigned short seed_16;
	unsigned int error_cnt;

	error_cnt = 0;

	/* test data bus */
	for(i=0;i<128;i++) {
		array[i] = ONEZERO;
	}
	flush_cpu_dcache();
	flush_l2_cache();
	for(i=0;i<128;i++) {
		if(array[i] != ONEZERO)
			error_cnt++;
	}

	for(i=0;i<128;i++) {
		array[i] = ZEROONE;
	}
	flush_cpu_dcache();
	flush_l2_cache();
	for(i=0;i<128;i++) {
		if(array[i] != ZEROONE)
			error_cnt++;
	}

	/* test counter or random data */
	seed_32 = 0;
	for(i=0;i<TEST_DATA_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, TEST_DATA_RANDOM);
		array[i] = seed_32;
	}

	seed_32 = 0;
	flush_cpu_dcache();
	flush_l2_cache();
	for(i=0;i<TEST_DATA_SIZE/4;i++) {
		seed_32 = seed_to_data_32(seed_32, TEST_DATA_RANDOM);
		if(array[i] != seed_32)
			error_cnt++;
	}

	/* test random addressing */
	seed_16 = 0;
	for(i=0;i<TEST_ADDR_SIZE/4;i++) {
		seed_16 = seed_to_data_16(seed_16, TEST_ADDR_RANDOM);
		array[(unsigned int) seed_16] = i;
	}

	seed_16 = 0;
	flush_cpu_dcache();
	flush_l2_cache();
	for(i=0;i<TEST_ADDR_SIZE/4;i++) {
		seed_16 = seed_to_data_16(seed_16, TEST_ADDR_RANDOM);
		if(array[(unsigned int) seed_16] != i)
			error_cnt++;
	}

	return error_cnt;
}

int memtest(void)
{
	unsigned int e;

	e = memtest_silent();
	if(e != 0) {
		printf("Memtest failed: %d/%d words incorrect\n", e, 2*128 + TEST_DATA_SIZE/4 + TEST_ADDR_SIZE/4);
		return 0;
	} else {
		printf("Memtest OK\n");
		return 1;
	}
}

int sdrinit(void)
{
	printf("Initializing SDRAM...\n");

	init_sequence();
#ifdef CSR_DDRPHY_BASE
	if(!sdrlevel())
		return 0;
#endif
	dfii_control_write(DFII_CONTROL_SEL);
	if(!memtest())
		return 0;

	return 1;
}

#endif
