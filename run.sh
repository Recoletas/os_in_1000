#!/bin/bash
CC=clang
OBJCOPY=llvm-objcopy
CFLAGS="-std=c11 -O2 -g3 -Wall -Wextra --target=riscv32 -ffreestanding -nostdlib -I."

# Build the shell (application)
$CC $CFLAGS -Wl,-Tuser/user.ld -Wl,-Map=user/shell.map -o user/shell.elf \
    user/shell.c user/user.c kernel/common.c
$OBJCOPY --set-section-flags .bss=alloc,contents -O binary user/shell.elf user/shell.bin
$OBJCOPY -Ibinary -Oelf32-littleriscv user/shell.bin user/shell.bin.o

# Build the kernel
$CC $CFLAGS -Wl,-Tkernel/kernel.ld -Wl,-Map=kernel/kernel.map -o kernel.elf \
    kernel/kernel.c kernel/common.c user/shell.bin.o