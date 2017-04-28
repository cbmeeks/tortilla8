#!/usr/bin/python3

import sys
import re       # Matching Op Code
import os       # Rom Loading
import time     # CPU Frequency
import random   # RND instruction
import argparse # Command line
from tortilla8_constants import *

# TODO raise real warnings
# TODO Wrap around doesn't work for drw instruction
# TODO Remove .lower() for regex match?
# TODO Shift L/R behavior needs a toggle for "old" and "new" behavior
# TODO Load for Halt till keypress is mega broken
# TODO Log a warning when running a unoffical instruction?
# TODO add comments

class guacamole:

    def __init__(self, rom=None, cpuhz=60, audiohz=60):
        self.ram = [None] * BYTES_OF_RAM

        self.register = [0]*16
        self.index_register = 0
        self.delay_timer_register = 0
        self.sound_timer_register = 0

        self.program_counter = PROGRAM_BEGIN_ADDRESS

        self.keypad = [False] * 16
        self.draw_flag = False

        # Stack emulation, always used
        self.stack = []
        self.stack_pointer = 0

        # Timming variables
        self.cpu_wait   = 1/cpuhz
        self.audio_wait = 1/audiohz
        self.audio_time = 0
        self.cpu_time   = 0

        random.seed()

        # Load Font, clear screen
        self.ram[FONT_ADDRESS:FONT_ADDRESS+len(FONT)] = [i for i in FONT]
        self.ram[GFX_ADDRESS:GFX_ADDRESS + GFX_RESOLUTION] = [0x00] * GFX_RESOLUTION

        # Load Rom
        if rom is not None:
            self.load_rom(rom)

    def load_rom(self, file_path):
        file_size = os.path.getsize(file_path)
        if file_size > MAX_ROM_SIZE:
            print("Warning: Rom file exceeds MAX_ROM_SIZE.")

        with open(file_path, "rb") as fh:
            self.ram[PROGRAM_BEGIN_ADDRESS:PROGRAM_BEGIN_ADDRESS + file_size] = [int.from_bytes(fh.read(1), 'big') for i in range(file_size)]

    def reset(self):
        self.__init__()

    def input_keys(self, pressed_keys):
        self.keypad = pressed_keys

    def output_screen(self):
        return self.ram[GFX_ADDRESS:GFX_ADDRESS+GFX_RESOLUTION]

    def output_draw_flag(self):
        if self.draw_falg:
            self.draw_falg = False
            return True
        return False

    def output_audio(self):
        return [self.delay_timer_register == 0, self.sound_timer_register == 0]

    def run(self):
        if self.cpu_wait <= (time.time() - self.cpu_time):
            self.cpu_time = time.time()
            self.cpu_tick()

        if self.audio_wait <= (time.time() - self.audio_time):
            self.audio_time = time.time()
            self.audio_tick()

    def cpu_tick(self):
        # Fetch instruction from ram
        flag = False
        instruction =  hex(self.ram[self.program_counter + 0])[2:].zfill(2)
        instruction += hex(self.ram[self.program_counter + 1])[2:].zfill(2)

        for reg_pattern in OP_REG:
            if re.match(reg_pattern.lower(), instruction):   # TODO probably should remove the need for .lower()
                #print(hex(self.program_counter) + " " + instruction + " " + OP_REG[reg_pattern][0])
                self.execute_op_code(OP_REG[reg_pattern][0],OP_REG[reg_pattern][1],instruction)
                flag = True
                break

        if not flag:
            print("Fatal: Unknown instruction " + instruction + " at " + hex(self.program_counter))

        self.program_counter += 2

    def audio_tick(self):
        # Decrement sound registers
        if self.delay_timer_register != 0:
            self.delay_timer_register -= 1
        if self.sound_timer_register != 0:
            self.sound_timer_register -= 1

    def execute_op_code(self, mnemonic, version, hex_code):
        # alias common stuff
        reg1       = int(hex_code[1],16)
        reg1_val   = self.register[reg1]
        reg2       = int(hex_code[2],16)
        reg2_val   = self.register[reg2]
        lower_byte = int(hex_code[2:4], 16)
        addr       = int(hex_code[1:4], 16)

        if mnemonic is 'cls':
            self.ram[GFX_ADDRESS:] = [0x00 for i in range(GFX_RESOLUTION)]

        elif mnemonic is 'ret':
            self.stack_pointer -= 1
            if self.stack_pointer < 0:
                print("Fatal: Stack underflow")
            self.program_counter =  self.stack.pop()

        elif mnemonic is 'sys':
            print("Warning: RCA 1802 call to " + hex(addr) + " was ignored.")

        elif mnemonic is 'call':
            if STACK_ADDRESS:
                self.ram[stack_pointer] = self.program_counter
            self.stack_pointer += 1
            self.stack.append(self.program_counter)
            if self.stack_pointer > STACK_SIZE:
                print("Warning: Stack overflow. Stack is now size " + self.stack_pointer)
            self.program_counter = addr - 2

        elif mnemonic is 'skp':
            if self.keypad[reg1_val & 0x0F]:
                self.program_counter += 2

        elif mnemonic is 'sknp':
            if not self.keypad[reg1_val & 0x0F]:
                self.program_counter += 2

        elif mnemonic is 'se':
            comp = lower_byte if "byte" in OP_CODES[mnemonic][version][OP_ARGS] else reg2_val
            if reg1_val == comp:
                self.program_counter += 2

        elif mnemonic is 'sne':
            comp = lower_byte if "byte" in OP_CODES[mnemonic][version][OP_ARGS] else reg2_val
            if reg1_val != comp:
                self.program_counter += 2

        elif mnemonic is 'shl':                                         #TODO add option to respect "old" shift
            self.register[reg1] = (reg1_val << 1) & 0xFF
            self.register[0xF] = 0xFF if reg1_val >= 0x80 else 0x0

        elif mnemonic is 'shr':                                         #TODO add option to respect "old" shift
            self.register[reg1] = reg1_val >> 1
            self.register[0xF] = 0xFF if (reg1_val % 2) == 1 else 0x0

        elif mnemonic is 'or':
            self.register[reg1] = reg1_val | reg2_val

        elif mnemonic is 'and':
            self.register[reg1] = reg1_val & reg2_val

        elif mnemonic is 'xor':
            self.register[reg1] = reg1_val ^ reg2_val

        elif mnemonic is 'sub':
            self.register[reg1] = reg1_val - reg2_val
            self.register[reg1] += 0x00 if reg1_val > reg2_val else 0xFF
            self.register[0xF] = 0xFF if reg1_val > reg2_val else 0x00

        elif mnemonic is 'subn':
            self.register[reg1] = reg2_val - reg1_val
            self.register[reg1] += 0x00 if reg2_val > reg1_val else 0xFF
            self.register[0xF] = 0xFF if reg2_val > reg1_val else 0x00

        elif mnemonic is 'jp':
            if 'v0' in OP_CODES[mnemonic][version][OP_ARGS]:
                self.program_counter = addr + self.register[0] - 2
            else:
                self.program_counter = addr - 2

        elif mnemonic is 'rnd':
            self.register[reg1] = random.randint(0, 255) & lower_byte

        elif mnemonic is 'add':
            if 'byte' in OP_CODES[mnemonic][version][OP_ARGS]:
                self.register[reg1] += lower_byte
            elif 'i' in OP_CODES[mnemonic][version][OP_ARGS]:
                self.index_register += reg1_val
            else:
                self.register[reg1] += reg2_val
                if reg1_val + reg2_val > 0xFF:
                    self.register[reg1] &= 0xFF

        elif mnemonic is 'ld':
            arg1 = OP_CODES[mnemonic][version][OP_ARGS][0]
            arg2 = OP_CODES[mnemonic][version][OP_ARGS][1]

            if 'register' is arg1:
                if   'byte'     is arg2: self.register[reg1] = lower_byte
                elif 'register' is arg2: self.register[reg1] = reg2_val
                elif 'dt'       is arg2: self.register[reg1] = self.delay_timer_register
                elif 'k'        is arg2:
                    original = ~int(''.join(['1' if x else '0' for x in self.keypad]),2)
                    new = 0x0000
                    while not (original & new):
                        new = int(''.join(['1' if x else '0' for x in self.keypad]),2)
                        #continue
                        break
                    self.register[reg1] = 1#new.find('1')          #TODO Hella Broken

                elif '[i]' == arg2:
                    for i in range(reg1):
                        self.register[i] = self.ram[self.index_register + i]

                else:
                    print("Fatal: Loads with argument type '" + arg2 + "' are not supported.")

            elif 'register' is arg2:
                if   'dt' is arg1: self.delay_timer_register = reg1_val
                elif 'st' is arg1: self.sound_timer_register = reg1_val
                elif 'f'  is arg1: self.index_register = FONT_ADDRESS + (5 * reg1_val)
                elif 'b'  is arg1:
                    reg1_val = str(reg1_val).zfill(3)
                    for i in range(3):
                        self.ram[self.index_register + i] = int(reg1_val[i])

                elif '[i]' == arg1:
                    for i in range(reg1):
                        self.ram[self.index_register + i] = self.register[i]

                else:
                    print("Fatal: Loads with argument type '" + arg1 + "' are not supported.")

            elif 'i' is arg1 and 'address' is arg2:
                self.index_register = addr

            else:
                print("Fatal: Loads with argument types '" + arg1 + "' and '" + arg2 +  "' are not supported.")

        elif mnemonic is 'drw':           # TODO Wrap around doesn't work
            if reg1_val >= GFX_WIDTH_PX:
                print("Warning: Draw instruction called with X origin >= GFX_WIDTH_PX\nWrap-around not yet supported.")
            if reg2_val >= GFX_HEIGHT_PX:
                print("Warning: Draw instruction called with Y origin >= GFX_HEIGHT_PX\nWrap-around not yet supported.")

            self.draw_flag = True
            height = int(hex_code[3],16)
            origin = GFX_ADDRESS + int(reg1_val/8) + (reg2_val * GFX_WIDTH) #To lowest byte
            mask = [0xFF >> (reg1_val%8)]
            mask.insert(0, ~mask[0])
            self.register[0xF] = 0x00

            for y in range(height):
                for x in range(2):
                    original = self.ram[origin + x + (y * GFX_WIDTH)]
                    self.ram[origin + x + (y * GFX_WIDTH)] ^= self.ram[self.index_register + y]
                    self.ram[origin + x + (y * GFX_WIDTH)] |= mask[x]
                    self.ram[origin + x + (y * GFX_WIDTH)] &= original
                    if ((self.ram[origin + x + (y * GFX_WIDTH)] ^ original) & original):
                        self.register[0xF] = 0xFF

        else:
            print("Fatal: Unknown mnemonic " + mnemonic )

    def dump_ram(self):
        for i,val in enumerate(self.ram):
            if val is None:
                print('0x' + hex(i)[2:].zfill(3))
            else:
                print('0x' + hex(i)[2:].zfill(3) + "  " + '0x' + hex(val)[2:].zfill(2))

def parse_args():
    parser = argparse.ArgumentParser(description='Guacamole is a Chip-8 emulator ...')
    parser.add_argument('rom', help='ROM to load and play.')
    parser.add_argument("-f","--frequency", default=60,help='Frequency (in Hz) to target.')
    opts = parser.parse_args()

    if not os.path.isfile(opts.rom):
        raise OSError("File '" + opts.rom + "' does not exist.")

    if opts.frequency:
        opts.frequency = int(opts.frequency)

    return opts

def main(opts):
    guac = guacamole(opts.rom, opts.frequency, opts.frequency)
    try:
        while True:
            guac.run()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main(parse_args())
