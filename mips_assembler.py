import re
import sys

# 1. 定义寄存器映射表
REGISTERS = {
    '0': 0, 'zero': 0, 'at': 1, 'v0': 2, 'v1': 3, 'a0': 4, 'a1': 5, 'a2': 6, 'a3': 7,
    't0': 8, 't1': 9, 't2': 10, 't3': 11, 't4': 12, 't5': 13, 't6': 14, 't7': 15,
    's0': 16, 's1': 17, 's2': 18, 's3': 19, 's4': 20, 's5': 21, 's6': 22, 's7': 23,
    't8': 24, 't9': 25, 'k0': 26, 'k1': 27, 'gp': 28, 'sp': 29, 'fp': 30, 'ra': 31
}

# 2. 指令编码信息 (Opcode, Funct等)
# R-Type: Opcode 恒为 0
R_TYPE = {
    'add': 0x20, 'sub': 0x22, 'and': 0x24, 'or': 0x25, 'xor': 0x26, 'nor': 0x27, 
    'slt': 0x2a, 'sll': 0x00, 'srl': 0x02, 'sra': 0x03, 'jr': 0x08, 'jalr': 0x09
}

# I-Type & J-Type Opcodes
OPCODES = {
    'addi': 0x08, 'slti': 0x0a, 'andi': 0x0c, 'ori': 0x0d, 'xori': 0x0e, 'lui': 0x0f,
    'beq': 0x04, 'blez': 0x06, 'bltz': 0x01, 
    'j': 0x02, 'jal': 0x03,
    'lb': 0x20, 'lh': 0x21, 'lw': 0x23, 'sb': 0x28, 'sh': 0x29, 'sw': 0x2b
}

def parse_reg(reg_str):
    """提取寄存器编号"""
    reg_str = reg_str.replace('$', '').replace(',', '').strip()
    if reg_str in REGISTERS:
        return REGISTERS[reg_str]
    return int(reg_str)

def to_twos_complement(val, bits):
    """将整数转换为补码位字符串"""
    if val < 0:
        val = (1 << bits) + val
    return format(val & ((1 << bits) - 1), f'0{bits}b')

class MIPSAssembler:
    def __init__(self):
        self.instructions = []
        self.labels = {}

    def preprocess(self, lines):
        """预处理：去除注释、空行、处理伪指令"""
        clean_lines = []
        for line in lines:
            # 去除注释
            line = line.split('#')[0].strip()
            if not line: continue
            
            # 处理标签
            if ':' in line:
                label_name, remaining = line.split(':', 1)
                self.labels[label_name.strip()] = len(clean_lines)
                line = remaining.strip()
                if not line: continue

            # 拆分助记符和操作数
            parts = re.split(r'[ \t]+', line, 1)
            mnemonic = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            # 伪指令展开
            if mnemonic == 'nop':
                clean_lines.append(['addi', '$0, $0, 0'])
            elif mnemonic == 'li':
                reg, val = args.split(',', 1)
                val = int(val.strip(), 0)
                if -32768 <= val <= 32767:
                    clean_lines.append(['addi', f'{reg}, $0, {val}'])
                else:
                    upper = (val >> 16) & 0xFFFF
                    lower = val & 0xFFFF
                    clean_lines.append(['lui', f'{reg}, {upper}'])
                    if lower != 0:
                        clean_lines.append(['ori', f'{reg}, {reg}, {lower}'])
            elif mnemonic == 'mv':
                rd, rs = args.split(',', 1)
                clean_lines.append(['addi', f'{rd}, {rs}, 0'])
            elif mnemonic == 'not':
                rd, rs = args.split(',', 1)
                clean_lines.append(['nor', f'{rd}, {rs}, $0'])
            elif mnemonic == 'neg':
                rd, rs = args.split(',', 1)
                clean_lines.append(['sub', f'{rd}, $0, {rs}'])
            else:
                clean_lines.append([mnemonic, args])
        return clean_lines

    def assemble(self, filename):
        with open(filename, 'r') as f:
            raw_lines = f.readlines()

        code_lines = self.preprocess(raw_lines)
        binary_output = []

        for i, (mnemonic, args_str) in enumerate(code_lines):
            args = [a.strip() for a in re.split(r',|(?<=\))\s*(?=\$)', args_str) if a.strip()]
            
            try:
                machine_code = 0
                
                # R-Type
                if mnemonic in R_TYPE:
                    opcode = 0
                    funct = R_TYPE[mnemonic]
                    if mnemonic in ['sll', 'srl', 'sra']: # rd, rt, sa
                        rd, rt, sa = parse_reg(args[0]), parse_reg(args[1]), int(args[2], 0)
                        machine_code = (opcode << 26) | (0 << 21) | (rt << 16) | (rd << 11) | (sa << 6) | funct
                    elif mnemonic == 'jr': # rs
                        rs = parse_reg(args[0])
                        machine_code = (opcode << 26) | (rs << 21) | (0 << 16) | (0 << 11) | (0 << 6) | funct
                    elif mnemonic == 'jalr': # rd, rs 或 rs
                        rd = parse_reg(args[0]) if len(args) > 1 else 31
                        rs = parse_reg(args[1]) if len(args) > 1 else parse_reg(args[0])
                        machine_code = (opcode << 26) | (rs << 21) | (0 << 16) | (rd << 11) | (0 << 6) | funct
                    else: # rd, rs, rt
                        rd, rs, rt = parse_reg(args[0]), parse_reg(args[1]), parse_reg(args[2])
                        machine_code = (opcode << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (0 << 6) | funct

                # J-Type
                elif mnemonic in ['j', 'jal']:
                    opcode = OPCODES[mnemonic]
                    target = self.labels[args[0]] if args[0] in self.labels else int(args[0], 0)
                    machine_code = (opcode << 26) | (target & 0x03FFFFFF)

                # I-Type
                elif mnemonic in OPCODES:
                    opcode = OPCODES[mnemonic]
                    if mnemonic in ['beq']: # rs, rt, label
                        rs, rt = parse_reg(args[0]), parse_reg(args[1])
                        target = self.labels[args[2]] if args[2] in self.labels else int(args[2], 0)
                        offset = target - (i + 1)
                        machine_code = (opcode << 26) | (rs << 21) | (rt << 16) | (offset & 0xFFFF)
                    elif mnemonic in ['blez', 'bltz']: # rs, label
                        rs = parse_reg(args[0])
                        rt = 0 if mnemonic == 'blez' else 0 # bltz rt 为 0
                        target = self.labels[args[1]] if args[1] in self.labels else int(args[1], 0)
                        offset = target - (i + 1)
                        machine_code = (opcode << 26) | (rs << 21) | (rt << 16) | (offset & 0xFFFF)
                    elif mnemonic in ['lw', 'sw', 'lb', 'sb', 'lh', 'sh']: # rt, offset(rs)
                        rt = parse_reg(args[0])
                        match = re.search(r'(-?\d+)\((\$\w+)\)', args[1])
                        imm = int(match.group(1), 0)
                        rs = parse_reg(match.group(2))
                        machine_code = (opcode << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
                    elif mnemonic == 'lui': # rt, imm
                        rt, imm = parse_reg(args[0]), int(args[1], 0)
                        machine_code = (opcode << 26) | (0 << 21) | (rt << 16) | (imm & 0xFFFF)
                    else: # rt, rs, imm (addi, andi...)
                        rt, rs, imm = parse_reg(args[0]), parse_reg(args[1]), int(args[2], 0)
                        machine_code = (opcode << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
                
                binary_output.append(format(machine_code, '08x'))

            except Exception as e:
                print(f"Error assembling line {i}: {mnemonic} {args_str}\n{e}")
                sys.exit(1)

        return binary_output

def write_coe(hex_list, out_file):
    with open(out_file, 'w') as f:
        f.write("; MIPS Instructions Generated by Python Assembler\n")
        f.write("memory_initialization_radix=16;\n")
        f.write("memory_initialization_vector=\n")
        for i, h in enumerate(hex_list):
            suffix = "," if i < len(hex_list) - 1 else ";"
            f.write(f"{h}{suffix}\n")

# 使用示例
if __name__ == "__main__":
    # 创建汇编器实例
    asm = MIPSAssembler()
    # 假设你的汇编文件叫 test.asm
    # 你可以手动创建一个 test.asm 把题目中的例子粘进去
    try:
        results = asm.assemble('mips.asm')
        write_coe(results, 'out.coe')
        print("Success! Output written to out.coe")
    except FileNotFoundError:
        print("Please create a 'test.asm' file first.")