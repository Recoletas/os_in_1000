import re
import sys

# 1. 寄存器映射 (支持 ABI 名和 x0-x31)
REGS = {
    'zero': 0, 'ra': 1, 'sp': 2, 'gp': 3, 'tp': 4, 't0': 5, 't1': 6, 't2': 7,
    's0': 8, 'fp': 8, 's1': 9, 'a0': 10, 'a1': 11, 'a2': 12, 'a3': 13, 'a4': 14,
    'a5': 15, 'a6': 16, 'a7': 17, 's2': 18, 's3': 19, 's4': 20, 's5': 21, 's6': 22,
    's7': 23, 's8': 24, 's9': 25, 's10': 26, 's11': 27, 't3': 28, 't4': 29, 't5': 30, 't6': 31
}
for i in range(32): REGS[f'x{i}'] = i

# 2. 指令格式与编码
OPCODES = {
    # R-type (Opcode=0110011)
    'add':  {'op': 0x33, 'f3': 0x0, 'f7': 0x00},
    'sub':  {'op': 0x33, 'f3': 0x0, 'f7': 0x20},
    'sll':  {'op': 0x33, 'f3': 0x1, 'f7': 0x00},
    'slt':  {'op': 0x33, 'f3': 0x2, 'f7': 0x00},
    'sltu': {'op': 0x33, 'f3': 0x3, 'f7': 0x00},
    'xor':  {'op': 0x33, 'f3': 0x4, 'f7': 0x00},
    'srl':  {'op': 0x33, 'f3': 0x5, 'f7': 0x00},
    'sra':  {'op': 0x33, 'f3': 0x5, 'f7': 0x20},
    'or':   {'op': 0x33, 'f3': 0x6, 'f7': 0x00},
    'and':  {'op': 0x33, 'f3': 0x7, 'f7': 0x00},
    # I-type (ALU)
    'addi': {'op': 0x13, 'f3': 0x0},
    'slti': {'op': 0x13, 'f3': 0x2},
    'andi': {'op': 0x13, 'f3': 0x7},
    'ori':  {'op': 0x13, 'f3': 0x6},
    'xori': {'op': 0x13, 'f3': 0x4},
    # I-type (Load)
    'lw':   {'op': 0x03, 'f3': 0x2},
    'lb':   {'op': 0x03, 'f3': 0x0},
    'lh':   {'op': 0x03, 'f3': 0x1},
    # I-type (JALR)
    'jalr': {'op': 0x67, 'f3': 0x0},
    # S-type (Store)
    'sw':   {'op': 0x23, 'f3': 0x2},
    'sb':   {'op': 0x23, 'f3': 0x0},
    'sh':   {'op': 0x23, 'f3': 0x1},
    # B-type (Branch)
    'beq':  {'op': 0x63, 'f3': 0x0},
    'bne':  {'op': 0x63, 'f3': 0x1},
    'blt':  {'op': 0x63, 'f3': 0x4},
    'bge':  {'op': 0x63, 'f3': 0x5},
    # U-type
    'lui':   {'op': 0x37},
    'auipc': {'op': 0x17},
    # J-type
    'jal':   {'op': 0x6f}
}

def parse_reg(s):
    s = s.replace(',', '').replace('$', '').strip()
    return REGS[s] if s in REGS else int(s.replace('x',''))

def get_bits(val, high, low):
    mask = (1 << (high - low + 1)) - 1
    return (val >> low) & mask

class RISCVAssembler:
    def __init__(self):
        self.labels = {}
        
    def assemble(self, file_path):
        with open(file_path, 'r') as f:
            lines = [l.split('#')[0].strip() for l in f if l.split('#')[0].strip()]

        # Pass 1: 处理标签和伪指令展开
        processed_code = []
        pc = 0
        for line in lines:
            if ':' in line:
                label, instr = line.split(':', 1)
                self.labels[label.strip()] = pc
                line = instr.strip()
                if not line: continue
            
            parts = re.split(r'[ \t]+', line, 1)
            op = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            # 伪指令展开
            if op == 'nop':
                processed_code.append(('addi', 'x0, x0, 0')); pc += 4
            elif op == 'li':
                rd, imm_s = args.split(',', 1)
                imm = int(imm_s.strip(), 0)
                # 简单实现：lui + addi
                upper = (imm + 0x800) >> 12
                lower = imm & 0xFFF
                processed_code.append(('lui', f'{rd}, {upper}')); pc += 4
                processed_code.append(('addi', f'{rd}, {rd}, {lower}')); pc += 4
            elif op == 'mv':
                rd, rs = args.split(',', 1)
                processed_code.append(('addi', f'{rd}, {rs}, 0')); pc += 4
            elif op == 'not':
                rd, rs = args.split(',', 1)
                processed_code.append(('xori', f'{rd}, {rs}, -1')); pc += 4
            elif op == 'neg':
                rd, rs = args.split(',', 1)
                processed_code.append(('sub', f'{rd}, x0, {rs}')); pc += 4
            elif op == 'j':
                processed_code.append(('jal', f'x0, {args}')); pc += 4
            else:
                processed_code.append((op, args)); pc += 4

        # Pass 2: 生成二进制
        binary_res = []
        pc = 0
        for op, args_s in processed_code:
            args = [a.strip() for a in re.split(r',|(?<=\))\s*(?=x|a|t|s|z|r|f|g|p)', args_s) if a.strip()]
            code = 0
            info = OPCODES[op]

            if info['op'] == 0x33: # R-type
                rd, rs1, rs2 = parse_reg(args[0]), parse_reg(args[1]), parse_reg(args[2])
                code = (info['f7'] << 25) | (rs2 << 20) | (rs1 << 15) | (info['f3'] << 12) | (rd << 7) | info['op']
            
            elif info['op'] in [0x13, 0x03, 0x67]: # I-type (ALU, Load, JALR)
                if '(' in args[1]: # lw rd, offset(rs1)
                    rd = parse_reg(args[0])
                    imm_s, rs1_s = args[1].split('(')
                    imm = int(imm_s, 0)
                    rs1 = parse_reg(rs1_s.replace(')', ''))
                else: # addi rd, rs1, imm
                    rd, rs1 = parse_reg(args[0]), parse_reg(args[1])
                    imm = int(args[2], 0)
                code = ((imm & 0xFFF) << 20) | (rs1 << 15) | (info.get('f3',0) << 12) | (rd << 7) | info['op']

            elif info['op'] == 0x23: # S-type (Store)
                rs2 = parse_reg(args[0])
                imm_s, rs1_s = args[1].split('(')
                imm = int(imm_s, 0)
                rs1 = parse_reg(rs1_s.replace(')', ''))
                imm_11_5 = get_bits(imm, 11, 5)
                imm_4_0 = get_bits(imm, 4, 0)
                code = (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (info['f3'] << 12) | (imm_4_0 << 7) | info['op']

            elif info['op'] == 0x63: # B-type (Branch)
                rs1, rs2 = parse_reg(args[0]), parse_reg(args[1])
                target = self.labels[args[2]] if args[2] in self.labels else int(args[2], 0)
                off = target - pc
                # RISC-V B-imm: [12|10:5|4:1|11]
                b12 = get_bits(off, 12, 12)
                b11 = get_bits(off, 11, 11)
                b10_5 = get_bits(off, 10, 5)
                b4_1 = get_bits(off, 4, 1)
                code = (b12 << 31) | (b10_5 << 25) | (rs2 << 20) | (rs1 << 15) | (info['f3'] << 12) | (b4_1 << 8) | (b11 << 7) | info['op']

            elif info['op'] in [0x37, 0x17]: # U-type (LUI, AUIPC)
                rd, imm = parse_reg(args[0]), int(args[1], 0)
                code = ((imm & 0xFFFFF) << 12) | (rd << 7) | info['op']

            elif info['op'] == 0x6f: # J-type (JAL)
                rd = parse_reg(args[0])
                target = self.labels[args[1]] if args[1] in self.labels else int(args[1], 0)
                off = target - pc
                # RISC-V J-imm: [20|10:1|11|19:12]
                j20 = get_bits(off, 20, 20)
                j19_12 = get_bits(off, 19, 12)
                j11 = get_bits(off, 11, 11)
                j10_1 = get_bits(off, 10, 1)
                code = (j20 << 31) | (j10_1 << 21) | (j11 << 20) | (j19_12 << 12) | (rd << 7) | info['op']

            binary_res.append(format(code & 0xFFFFFFFF, '08x'))
            pc += 4
        return binary_res

def write_coe(hex_list, out_file):
    with open(out_file, 'w') as f:
        f.write("memory_initialization_radix=16;\nmemory_initialization_vector=\n")
        f.writelines([h + (",\n" if i < len(hex_list)-1 else ";") for i, h in enumerate(hex_list)])

if __name__ == "__main__":
    asm = RISCVAssembler()
    res = asm.assemble('test2.asm')
    write_coe(res, 'riscv_out.coe')
    print("RISC-V Assembly complete. Output: riscv_out.coe")