#include <generated/csr.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <id.h>


void get_ident(char *ident)
{
#ifdef CSR_IDENTIFIER_BASE
    int len, i;
    
    identifier_address_write(0);
    len = identifier_data_read();
    for(i=0;i<len;i++) {
        identifier_address_write(i+1);
        ident[i] = identifier_data_read();
    }
    ident[i] = 0;
#else
    ident[0] = 0;
#endif
}
