#include "common.h"
#include "kernel.h"

#define PROC_UNUSED   0
#define PROC_RUNNABLE 1
#define PROCS_MAX     8

extern char __bss[], __bss_end[], __stack_top[];
extern char __free_ram[], __free_ram_end[];
extern char __kernel_base[];
extern char _binary_shell_bin_start[], _binary_shell_bin_size[];

struct process procs[PROCS_MAX];
struct process *current_proc;
struct process *idle_proc;

// 声明外部函数和汇编标签
void user_entry(void);
void switch_context(uint32_t *prev_sp, uint32_t *next_sp);
void kernel_entry(void);

// 映射页面函数
void map_page(uint32_t *table1, uint32_t vaddr, paddr_t paddr, uint32_t flags) {
    uint32_t vpn1 = (vaddr >> 22) & 0x3ff;
    if ((table1[vpn1] & PAGE_V) == 0) {
        uint32_t pt_paddr = alloc_pages(1);
        table1[vpn1] = ((pt_paddr / PAGE_SIZE) << 10) | PAGE_V;
    }

    uint32_t vpn0 = (vaddr >> 12) & 0x3ff;
    uint32_t *table0 = (uint32_t *) ((table1[vpn1] >> 10) * PAGE_SIZE);
    table0[vpn0] = ((paddr / PAGE_SIZE) << 10) | flags | PAGE_V;
}

// 进程创建函数
struct process *create_process(const void *image, size_t image_size) {
    struct process *proc = NULL;
    int i;
    for (i = 0; i < PROCS_MAX; i++) {
        if (procs[i].state == PROC_UNUSED) {
            proc = &procs[i];
            break;
        }
    }

    if (!proc) PANIC("no free process slots");

    uint32_t *sp = (uint32_t *) &proc->stack[sizeof(proc->stack)];

    // 初始化内核页表
    uint32_t *page_table = (uint32_t *) alloc_pages(1);
    for (paddr_t paddr = (paddr_t) __kernel_base;
         paddr < (paddr_t) __free_ram_end; paddr += PAGE_SIZE) {
        map_page(page_table, paddr, paddr, PAGE_R | PAGE_W | PAGE_X);
    }

    if (image) {
        // --- 用户进程逻辑 ---
        for (uint32_t off = 0; off < image_size; off += PAGE_SIZE) {
            paddr_t page = alloc_pages(1);
            size_t remaining = image_size - off;
            size_t copy_size = PAGE_SIZE <= remaining ? PAGE_SIZE : remaining;
            memcpy((void *) page, (uint8_t *)image + off, copy_size);
            // 映射到用户空间虚拟地址 USER_BASE
            map_page(page_table, USER_BASE + off, page, PAGE_U | PAGE_R | PAGE_W | PAGE_X);
        }
        // 用户进程第一次切换后应该跳转到 user_entry
        *--sp = (uint32_t) user_entry; 
    } else {
        // --- 内核进程逻辑 (如 Idle) ---
        // 注意：这里为了兼容，如果不是用户进程且不是idle，
        // 我们假设在 kernel_main 中会手动处理入口地址。
        // 在该版本中，内核任务 A/B 建议改为通过 pc 参数传递，
        // 但为了符合你的结构，我们统一处理。
        *--sp = 0; 
    }

    // 设置 switch_context 需要恢复的寄存器 (s0-s11)
    for (int j = 0; j < 12; j++) *--sp = 0;

    proc->pid = i + 1;
    proc->state = PROC_RUNNABLE;
    proc->sp = (uint32_t) sp;
    proc->page_table = page_table;
    return proc;
}

// 特殊处理内核线程 A/B 的创建（因为它们不需要镜像映射）
struct process *create_kernel_thread(void (*entry)(void)) {
    struct process *proc = create_process(NULL, 0);
    uint32_t *sp = (uint32_t *) proc->sp;
    // 覆盖原本压入的 ra (在 switch_context 栈帧中 ra 是第一个)
    // 我们的 switch_context 压栈顺序是 ra, s0-s11, 所以 ra 在偏移 12 的位置
    sp[12] = (uint32_t) entry; 
    return proc;
}

void yield(void) {
    struct process *next = idle_proc;
    for (int i = 0; i < PROCS_MAX; i++) {
        struct process *proc = &procs[(current_proc->pid + i) % PROCS_MAX];
        if (proc->state == PROC_RUNNABLE && proc->pid > 0) {
            next = proc;
            break;
        }
    }

    if (next == current_proc) return;

    // 更新 SATP 切换页表，更新 sscratch 为下个进程的内核栈顶
    __asm__ __volatile__(
        "sfence.vma\n"
        "csrw satp, %[satp]\n"
        "sfence.vma\n"
        "csrw sscratch, %[sscratch]\n"
        :
        : [satp] "r" (SATP_SV32 | ((uint32_t) next->page_table / PAGE_SIZE)),
          [sscratch] "r" ((uint32_t) &next->stack[sizeof(next->stack)])
    );
    
    struct process *prev = current_proc;
    current_proc = next;
    switch_context(&prev->sp, &next->sp);
}

// 核心：跳转到用户态的实现
__attribute__((naked)) void user_entry(void) {
    __asm__ __volatile__(
        "csrw sepc, %[sepc]\n"       // 用户程序起始地址
        "csrw sstatus, %[sstatus]\n" // 设置 SPP=0 (进入U-Mode), SPIE=1
        "sret\n"
        :
        : [sepc] "r" (USER_BASE),
          [sstatus] "r" (SSTATUS_SPIE) // SSTATUS_SPP 为 0
    );
}

void kernel_main(void) { 
    memset(__bss, 0, (size_t) __bss_end - (size_t) __bss);
    printf("\n\nOS is booting...\n");

    WRITE_CSR(stvec, (uint32_t) kernel_entry);

    // 1. 创建空闲进程
    idle_proc = create_process(NULL, 0); 
    idle_proc->pid = 0;
    current_proc = idle_proc;

    // 2. 创建内核进程 A 和 B
    // 使用修正后的函数以处理入口点地址
    extern void proc_a_entry(void);
    extern void proc_b_entry(void);
    create_kernel_thread(proc_a_entry);
    create_kernel_thread(proc_b_entry);

    // 3. 创建用户进程 (Shell)
    create_process(_binary_shell_bin_start, (size_t) _binary_shell_bin_size);
    
    printf("Starting scheduler...\n");
    yield();

    PANIC("switched to idle process");
}

// 其余辅助函数 (alloc_pages, map_page 等保持你提供的修复后逻辑)
paddr_t alloc_pages(uint32_t n) {
    static paddr_t next_paddr = (paddr_t) __free_ram;
    paddr_t paddr = next_paddr;
    next_paddr += n * PAGE_SIZE;
    if (next_paddr > (paddr_t) __free_ram_end) PANIC("out of memory");
    memset((void *) paddr, 0, n * PAGE_SIZE);
    return paddr;
}

void handle_trap(struct trap_frame *f) {
    uint32_t scause = READ_CSR(scause);
    uint32_t stval = READ_CSR(stval);
    uint32_t sepc = READ_CSR(sepc);
    PANIC("unexpected trap scause=%x, stval=%x, sepc=%x\n", scause, stval, sepc);
}