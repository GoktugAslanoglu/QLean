    .section .text.boot, "ax", @progbits
    .globl _start
    .type _start, @function
_start:
    lui sp, 8
    li a0, 0
    li a7, 93
    ecall
.Lrequest:
    call qlean_request
    li a7, 93
    ecall
    j .Lrequest
    .size _start, . - _start
