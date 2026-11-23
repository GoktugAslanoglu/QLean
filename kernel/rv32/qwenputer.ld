OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY {
    ROM  (rx) : ORIGIN = 0x40000, LENGTH = 256K
    DROM (r)  : ORIGIN = 0x20000, LENGTH = 128K
    RAM  (rw) : ORIGIN = 0x00100, LENGTH = 0x7f00
}

PHDRS {
    text PT_LOAD FLAGS(5);
    drom PT_LOAD FLAGS(4);
    ram  PT_LOAD FLAGS(6);
}

SECTIONS {
    .text : { KEEP(*(.text.boot)) *(.text .text.*) } > ROM :text
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) } > DROM :drom
    .data : { *(.data .data.* .sdata .sdata.*) } > RAM :ram
    .bss (NOLOAD) : {
        *(.bss.ql_arena)
        *(.bss .bss.* .sbss .sbss.*)
        *(COMMON)
    } > RAM :ram

    __static_end = ADDR(.bss) + SIZEOF(.bss);
    __stack_top = 0x8000;
    __stack_floor = __stack_top - 4K;
    ASSERT(SIZEOF(.text) <= 64K, "QLean text exceeds 64 KiB")
    ASSERT(SIZEOF(.rodata) <= 16K, "QLean DROM exceeds 16 KiB")
    ASSERT(__static_end - ORIGIN(RAM) <= 24K, "QLean static RAM exceeds 24 KiB")
    ASSERT(__static_end <= __stack_floor, "QLean static data overlaps stack")

    /DISCARD/ : { *(.comment .note* .eh_frame*) }
}
