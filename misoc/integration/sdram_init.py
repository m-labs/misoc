import jinja2
from jinja2 import Template
from migen import log2_int


def _get_sdram_phy_sequence(sdram_phy_settings):
    nphases = sdram_phy_settings.nphases
    cl = sdram_phy_settings.cl

    consts = {}
    cmds = {
        "PRECHARGE_ALL": "DFII_COMMAND_RAS|DFII_COMMAND_WE|DFII_COMMAND_CS",
        "MODE_REGISTER": "DFII_COMMAND_RAS|DFII_COMMAND_CAS|DFII_COMMAND_WE|DFII_COMMAND_CS",
        "AUTO_REFRESH":  "DFII_COMMAND_RAS|DFII_COMMAND_CAS|DFII_COMMAND_CS",
        "UNRESET":       "DFII_CONTROL_ODT|DFII_CONTROL_RESET_N",
        "CKE":           "DFII_CONTROL_CKE|DFII_CONTROL_ODT|DFII_CONTROL_RESET_N"
    }

    if sdram_phy_settings.memtype == "SDR":
        bl = sdram_phy_settings.nphases
        mr = log2_int(bl) + (cl << 4)
        reset_dll = 1 << 8

        init_sequence = [
            ("Bring CKE high", 0x0000, 0, cmds["CKE"], 20000),
            ("Precharge All",  0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Load Mode Register / Reset DLL, CL={0:d}, BL={1:d}".format(cl, bl),
             mr + reset_dll, 0, cmds["MODE_REGISTER"], 200),
            ("Precharge All", 0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Load Mode Register / CL={0:d}, BL={1:d}".format(cl, bl),
             mr, 0, cmds["MODE_REGISTER"], 200)
        ]

    elif sdram_phy_settings.memtype == "DDR":
        bl = 2*sdram_phy_settings.nphases
        mr  = log2_int(bl) + (cl << 4)
        emr = 0
        reset_dll = 1 << 8

        init_sequence = [
            ("Bring CKE high", 0x0000, 0, cmds["CKE"], 20000),
            ("Precharge All",  0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Load Extended Mode Register", emr, 1, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register / Reset DLL, CL={0:d}, BL={1:d}".format(cl, bl),
             mr + reset_dll, 0, cmds["MODE_REGISTER"], 200),
            ("Precharge All", 0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Load Mode Register / CL={0:d}, BL={1:d}".format(cl, bl),
             mr, 0, cmds["MODE_REGISTER"], 200)
        ]

    elif sdram_phy_settings.memtype == "LPDDR":
        bl = 2*sdram_phy_settings.nphases
        mr  = log2_int(bl) + (cl << 4)
        emr = 0
        reset_dll = 1 << 8

        init_sequence = [
            ("Bring CKE high", 0x0000, 0, cmds["CKE"], 20000),
            ("Precharge All",  0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Load Extended Mode Register", emr, 2, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register / Reset DLL, CL={0:d}, BL={1:d}".format(cl, bl),
             mr + reset_dll, 0, cmds["MODE_REGISTER"], 200),
            ("Precharge All", 0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Load Mode Register / CL={0:d}, BL={1:d}".format(cl, bl),
             mr, 0, cmds["MODE_REGISTER"], 200)
        ]

    elif sdram_phy_settings.memtype == "DDR2":
        bl = 2*sdram_phy_settings.nphases
        wr = 2
        mr = log2_int(bl) + (cl << 4) + (wr << 9)
        emr = 0
        emr2 = 0
        emr3 = 0
        reset_dll = 1 << 8
        ocd = 7 << 7

        init_sequence = [
            ("Bring CKE high", 0x0000, 0, cmds["CKE"], 20000),
            ("Precharge All",  0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Load Extended Mode Register 3", emr3, 3, cmds["MODE_REGISTER"], 0),
            ("Load Extended Mode Register 2", emr2, 2, cmds["MODE_REGISTER"], 0),
            ("Load Extended Mode Register", emr, 1, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register / Reset DLL, CL={0:d}, BL={1:d}".format(cl, bl),
             mr + reset_dll, 0, cmds["MODE_REGISTER"], 200),
            ("Precharge All", 0x0400, 0, cmds["PRECHARGE_ALL"], 0),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Auto Refresh", 0x0, 0, cmds["AUTO_REFRESH"], 4),
            ("Load Mode Register / CL={0:d}, BL={1:d}".format(cl, bl),
             mr, 0, cmds["MODE_REGISTER"], 200),
            ("Load Extended Mode Register / OCD Default", emr+ocd, 1, cmds["MODE_REGISTER"], 0),
            ("Load Extended Mode Register / OCD Exit", emr, 1, cmds["MODE_REGISTER"], 0),
        ]
    elif sdram_phy_settings.memtype == "DDR3":
        bl = 2*sdram_phy_settings.nphases

        def format_mr0(bl, cl, wr, dll_reset):
            bl_to_mr0 = {
                4: 0b10,
                8: 0b00
            }
            cl_to_mr0 = {
                 5: 0b0010,
                 6: 0b0100,
                 7: 0b0110,
                 8: 0b1000,
                 9: 0b1010,
                10: 0b1100,
                11: 0b1110,
                12: 0b0001,
                13: 0b0011,
                14: 0b0101
            }
            wr_to_mr0 = {
                16: 0b000,
                 5: 0b001,
                 6: 0b010,
                 7: 0b011,
                 8: 0b100,
                10: 0b101,
                12: 0b110,
                14: 0b111
            }
            mr0 = bl_to_mr0[bl]
            mr0 |= (cl_to_mr0[cl] & 1) << 2
            mr0 |= ((cl_to_mr0[cl] >> 1) & 0b111) << 4
            mr0 |= dll_reset << 8
            mr0 |= wr_to_mr0[wr] << 9
            return mr0

        def format_mr1(output_drive_strength, rtt_nom):
            mr1 = ((output_drive_strength >> 0) & 1) << 1
            mr1 |= ((output_drive_strength >> 1) & 1) << 5
            mr1 |= ((rtt_nom >> 0) & 1) << 2
            mr1 |= ((rtt_nom >> 1) & 1) << 6
            mr1 |= ((rtt_nom >> 2) & 1) << 9
            return mr1

        def format_mr2(cwl, rtt_wr):
            mr2 = (cwl-5) << 3
            mr2 |= rtt_wr << 9
            return mr2

        mr0 = format_mr0(bl, cl, 8, 1)  # wr=8 FIXME: this should be ceiling(tWR/tCK)
        mr1 = format_mr1(1, 1)  # Output Drive Strength RZQ/7 (34 ohm) / Rtt RZQ/4 (60 ohm)
        mr2 = format_mr2(sdram_phy_settings.cwl, 2)  # Rtt(WR) RZQ/4
        mr3 = 0

        init_sequence = [
            ("Release reset", 0x0000, 0, cmds["UNRESET"], 50000),
            ("Bring CKE high", 0x0000, 0, cmds["CKE"], 10000),
            ("Load Mode Register 2", mr2, 2, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register 3", mr3, 3, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register 1", mr1, 1, cmds["MODE_REGISTER"], 0),
            ("Load Mode Register 0, CL={0:d}, BL={1:d}".format(cl, bl),
             mr0, 0, cmds["MODE_REGISTER"], 200),
            ("ZQ Calibration", 0x0400, 0, "DFII_COMMAND_WE|DFII_COMMAND_CS", 200),
        ]

        # the value of MR1 needs to be modified during write leveling
        consts["DDR3_MR1"] = mr1
    else:
        raise NotImplementedError("Unsupported memory type: "+sdram_phy_settings.memtype)

    return {
        "nphases": sdram_phy_settings.nphases,
        "rdphase": sdram_phy_settings.rdphase,
        "wrphase": sdram_phy_settings.wrphase,
        "consts": consts,
        "init_sequence": init_sequence
    }


def get_sdram_phy_header(sdram_phy_settings):
    return Template("""\
#ifndef __GENERATED_SDRAM_PHY_H
#define __GENERATED_SDRAM_PHY_H

#include <hw/common.h>
#include <generated/csr.h>
#include <hw/flags.h>

#define DFII_NPHASES {{nphases}}

static void cdelay(int i);
{% for n in range(nphases) %}
static void command_p{{n}}(int cmd)
{
    dfii_pi{{n}}_command_write(cmd);
    dfii_pi{{n}}_command_issue_write(1);
}
{% endfor %}

#define dfii_pird_address_write(X) dfii_pi{{rdphase}}_address_write(X)
#define dfii_piwr_address_write(X) dfii_pi{{wrphase}}_address_write(X)

#define dfii_pird_baddress_write(X) dfii_pi{{rdphase}}_baddress_write(X)
#define dfii_piwr_baddress_write(X) dfii_pi{{wrphase}}_baddress_write(X)

#define command_prd(X) command_p{{rdphase}}(X)
#define command_pwr(X) command_p{{wrphase}}(X)

#define DFII_PIX_DATA_SIZE CSR_DFII_PI0_WRDATA_SIZE

const unsigned int dfii_pix_wrdata_addr[{{nphases}}] = {
{%- for n in range(nphases) %}
    CSR_DFII_PI{{n}}_WRDATA_ADDR,
{%- endfor %}
};

const unsigned int dfii_pix_rddata_addr[{{nphases}}] = {
{%- for n in range(nphases) %}
    CSR_DFII_PI{{n}}_RDDATA_ADDR,
{%- endfor %}
};
{% for name in consts %}
#define {{name}} {{consts[name]}}
{% endfor %}

static void init_sequence(void)
{
{%- for comment, a, ba, cmd, delay in init_sequence %}
    /* {{comment}} */
    dfii_pi0_address_write(0x{{"%0x"|format(a)}});
    dfii_pi0_baddress_write({{ba}});
    {% if cmd[:12] == "DFII_CONTROL" -%}
        dfii_control_write({{cmd}});
    {%- else -%}
        command_p0({{cmd}});
    {%- endif %}
    {% if delay > 0 -%}
        cdelay({{delay}});
    {%- endif %}
{% endfor -%}
}
#endif
""").render(**_get_sdram_phy_sequence(sdram_phy_settings))


def get_sdram_phy_rust(sdram_phy_settings):
    return Template("""\
// Include this file as:
//     include!(concat!(env!("BUILDINC_DIRECTORY"), "/generated/sdram_phy.rs"));
#[allow(dead_code)]
pub mod sdram_phy {
    use csr;

    pub fn spin_cycles(mut cycles: usize) {
        while cycles > 0 {
            unsafe { asm!(""::::"volatile") }
            cycles -= 1;
        }
    }

    pub const DFII_CONTROL_SEL:     u8 = 0x01;
    pub const DFII_CONTROL_CKE:     u8 = 0x02;
    pub const DFII_CONTROL_ODT:     u8 = 0x04;
    pub const DFII_CONTROL_RESET_N: u8 = 0x08;

    pub const DFII_COMMAND_CS:      u8 = 0x01;
    pub const DFII_COMMAND_WE:      u8 = 0x02;
    pub const DFII_COMMAND_CAS:     u8 = 0x04;
    pub const DFII_COMMAND_RAS:     u8 = 0x08;
    pub const DFII_COMMAND_WRDATA:  u8 = 0x10;
    pub const DFII_COMMAND_RDDATA:  u8 = 0x20;

    pub const DFII_NPHASES: usize = {{nphases}};

    {% for n in range(nphases) %}
    pub unsafe fn command_p{{n}}(cmd: u8) {
        csr::dfii::pi{{n}}_command_write(cmd);
        csr::dfii::pi{{n}}_command_issue_write(1);
    }
    {% endfor %}

    pub unsafe fn dfii_pird_address_write(a: u16) { csr::dfii::pi{{rdphase}}_address_write(a) }
    pub unsafe fn dfii_piwr_address_write(a: u16) { csr::dfii::pi{{wrphase}}_address_write(a) }

    pub unsafe fn dfii_pird_baddress_write(a: u8) { csr::dfii::pi{{rdphase}}_baddress_write(a) }
    pub unsafe fn dfii_piwr_baddress_write(a: u8) { csr::dfii::pi{{wrphase}}_baddress_write(a) }

    pub unsafe fn command_prd(cmd: u8) { command_p{{rdphase}}(cmd) }
    pub unsafe fn command_pwr(cmd: u8) { command_p{{wrphase}}(cmd) }

    pub const DFII_PIX_DATA_SIZE: usize = csr::dfii::PI0_WRDATA_SIZE;

    pub const DFII_PIX_WRDATA_ADDR: [*mut u32; {{nphases}}] = [
    {%- for n in range(nphases) %}
        csr::dfii::PI{{n}}_WRDATA_ADDR,
    {%- endfor %}
    ];

    pub const DFII_PIX_RDDATA_ADDR: [*mut u32; {{nphases}}] = [
    {%- for n in range(nphases) %}
        csr::dfii::PI{{n}}_RDDATA_ADDR,
    {%- endfor %}
    ];

    {% for name in consts %}
    pub const {{name}}: u32 = {{consts[name]}};
    {% endfor %}

    pub unsafe fn initialize() {
    {%- for comment, a, ba, cmd, delay in init_sequence %}
        /* {{comment}} */
        csr::dfii::pi0_address_write(0x{{"%0x"|format(a)}});
        csr::dfii::pi0_baddress_write({{ba}});
        {% if cmd[:12] == "DFII_CONTROL" -%}
            csr::dfii::control_write({{cmd}});
        {%- else -%}
            command_p0({{cmd}});
        {%- endif %}
        {% if delay > 0 -%}
            spin_cycles({{delay}});
        {%- endif %}
    {% endfor -%}
    }
}
""").render(**_get_sdram_phy_sequence(sdram_phy_settings))
