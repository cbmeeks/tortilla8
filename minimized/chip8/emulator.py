#!/usr/bin/env python3

from re import match
from random import randint
from os.path import getsize
from time import time
from collections import namedtuple

OP_CODES = (
    ('cls' , ('00e0',())),
    ('ret' , ('00ee',())),
    ('sys' , ('0(^0)..',('addr',))), # prevent match to cls or ret
    ('call', ('2...',('addr',))),
    ('skp' , ('e.9e',('reg',))),
    ('sknp', ('e.a1',('reg',))),
    ('se'  ,(('5..0',('reg','reg')),
             ('3...',('reg','byte')))),
    ('sne' ,(('9..0',('reg','reg')),
             ('4...',('reg','byte')))),
    ('add' ,(('7...',('reg','byte')),
             ('8..4',('reg','reg')),
             ('f.1e',('i','reg')))),
    ('or'  , ('8..1',('reg','reg'))),
    ('and' , ('8..2',('reg','reg'))),
    ('xor' , ('8..3',('reg','reg'))),
    ('sub' , ('8..5',('reg','reg'))),
    ('subn', ('8..7',('reg','reg'))),
    ('shr' ,(('8..6',('reg',)),
             ('    ',('reg','reg')))), # Blank regex, we never match, use Legacy_shift instead
    ('shl' ,(('8..e',('reg',)),
             ('    ',('reg','reg')))), # as above
    ('rnd' , ('c...',('reg','byte'))),
    ('jp'  ,(('b...',('v0','addr')),
             ('1...',('addr',)))),
    ('ld'  ,(('6...',('reg','byte')),
             ('8..0',('reg','reg')),
             ('f.07',('reg','dt')),
             ('f.0a',('reg','k')),
             ('f.65',('reg','(i)')),
             ('a...',('i','addr')),
             ('f.15',('dt','reg')),
             ('f.18',('st','reg')),
             ('f.29',('f','reg')),
             ('f.33',('b','reg')),
             ('f.55',('(i)','reg')))),
    ('drw' , ('d...',('reg','reg','nibble')))
)

class ASMdata( namedtuple('ASMdata', 'hex_instruction valid mnemonic\
    mnemonic_arg_types disassembled_line unoffical_op banned super8') ):
    pass

def explode_op_codes( op_code_list ):
    exploded_list = []
    for item in op_code_list:
        if item.find('.') == -1:
            exploded_list.append(item)
        else:
            upper,repl,fill = 16,'.',1
            if item[2:] == '..':
                upper,repl,fill = 256,'..',2
            for i in range(0, upper):
                exploded_list.append(item.replace(repl, hex(i)[2:].zfill(fill)))
    return exploded_list

class RomLoadError(Exception): pass
class StackUnderflowError(Exception): pass
class StackOverflowError(Exception): pass
class InvalidInstructionError(Exception): pass
class DisassemblerError(Exception): pass

class Emulator:

    SET_VF_ON_GFX_OVERFLOW = False # Undocumented 'feature'. When 'Add I, VX' overflows 'I'
                                   # VF is set to one when this is True. The insturction does
                                   # not set VF low. Used by Spacefight 2019.
    ENABLE_LEGACY_SHIFT = False # Legacy Shift is performed by copying y into x and shifting,
                                # rather than shifting x. Not sure who uses this.
    NUMB_OF_REGS = 16
    BYTES_OF_RAM = 4096
    MAX_ROM_SIZE = 3232
    PROGRAM_BEGIN_ADDRESS = 0x200 # Some use 0x600

    STACK_SIZE    = 12
    STACK_ADDRESS = None

    GFX_ADDRESS    = 0xF00
    GFX_HEIGHT_PX  = 32
    GFX_WIDTH_PX   = 64
    GFX_WIDTH      = 8
    GFX_RESOLUTION = 8*32 #In bytes

    GFX_FONT_ADDRESS = 0x050
    GFX_FONT = (
        0xF0, 0x90, 0x90, 0x90, 0xF0, 0x20, 0x60, 0x20, 0x20, 0x70, # 0 1
        0xF0, 0x10, 0xF0, 0x80, 0xF0, 0xF0, 0x10, 0xF0, 0x10, 0xF0, # 2 3
        0x90, 0x90, 0xF0, 0x10, 0x10, 0xF0, 0x80, 0xF0, 0x10, 0xF0, # 4 5
        0xF0, 0x80, 0xF0, 0x90, 0xF0, 0xF0, 0x10, 0x20, 0x40, 0x40, # 6 7
        0xF0, 0x90, 0xF0, 0x90, 0xF0, 0xF0, 0x90, 0xF0, 0x10, 0xF0, # 8 9
        0xF0, 0x90, 0xF0, 0x90, 0x90, 0xE0, 0x90, 0xE0, 0x90, 0xE0, # A B
        0xF0, 0x80, 0x80, 0x80, 0xF0, 0xE0, 0x90, 0x90, 0x90, 0xE0, # C D
        0xF0, 0x80, 0xF0, 0x80, 0xF0, 0xF0, 0x80, 0xF0, 0x80, 0x80  # E F
    )

    OP_CODE_SIZE = 2
    UNOFFICIAL_OP_CODES = ('xor','shr','shl','subn') # But still supported
    BANNED_OP_CODES = ('7f..','8f.4','8f.6','8f.e','cf..','6f..','8f.0','ff07','ff0a','ff65') # Ins that modify VF: add, shr, shl, rnd, ld
    SUPER_CHIP_OP_CODES = ('00c.','00fb','00fc','00fd','00fe','00ff','d..0','f.30','f.75','f.85') # Super chip-8, not supported
    BANNED_OP_CODES_EXPLODED = explode_op_codes(BANNED_OP_CODES)
    SUPER_CHIP_OP_CODES_EXPLODED = explode_op_codes(SUPER_CHIP_OP_CODES)

    def __init__(self, rom=None, cpuhz=200, audiohz=60, delayhz=60):

        # RAM
        self.ram = [0x00] * Emulator.BYTES_OF_RAM

        # Registers
        self.register = [0x00] * Emulator.NUMB_OF_REGS
        self.index_register = 0x000
        self.delay_timer_register = 0x00
        self.sound_timer_register = 0x00

        # Current dissassembled instruction / OP Code
        self.dis_ins = None

        # Program Counter
        self.program_counter = Emulator.PROGRAM_BEGIN_ADDRESS
        self.calling_pc      = Emulator.PROGRAM_BEGIN_ADDRESS

        # I/O
        self.keypad      = [False] * 16
        self.prev_keypad = 0
        self.draw_flag   = False
        self.waiting_for_key = False
        self.spinning = False

        # Stack
        self.stack = []
        self.stack_pointer = 0

        # Timming variables
        self.cpu_wait   = 1/cpuhz
        self.audio_wait = 1/audiohz
        self.delay_wait = 1/delayhz
        self._cpu_time = 0
        self._audio_time = 0
        self._delay_time = 0

        # Load Font, clear screen
        self.ram[Emulator.GFX_FONT_ADDRESS:Emulator.GFX_FONT_ADDRESS + len(Emulator.GFX_FONT)] = Emulator.GFX_FONT
        self.ram[Emulator.GFX_ADDRESS:Emulator.GFX_ADDRESS + Emulator.GFX_RESOLUTION] = [0x00] * Emulator.GFX_RESOLUTION

        # Load Rom
        if rom is not None:
            self.load_rom(rom)

        # Instruction lookup table
        self.ins_tbl={
        'cls' :i_cls, 'ret' :i_ret,  'sys' :i_sys, 'call':i_call,
        'skp' :i_skp, 'sknp':i_sknp, 'se'  :i_se,  'sne' :i_sne,
        'add' :i_add, 'or'  :i_or,   'and' :i_and, 'xor' :i_xor,
        'sub' :i_sub, 'subn':i_subn, 'shr' :i_shr, 'shl' :i_shl,
        'rnd' :i_rnd, 'jp'  :i_jp,   'ld'  :i_ld,  'drw' :i_drw}

    def load_rom(self, file_path):
        '''
        Loads a Chip-8 ROM from a file into the RAM.
        '''
        file_size = getsize(file_path)
        if file_size > Emulator.MAX_ROM_SIZE:
            raise RomLoadError

        with open(file_path, "rb") as fh:
            self.ram[Emulator.PROGRAM_BEGIN_ADDRESS:Emulator.PROGRAM_BEGIN_ADDRESS + file_size] = \
                [int.from_bytes(fh.read(1), 'big') for i in range(file_size)]

    def run(self):
        '''
        Attempt to run the next instruction. This should be called as a part
        of the main loop, it insures that the CPU and timers execute at the
        target frequency.
        '''
        t = time()
        if self.cpu_wait <= (t - self._cpu_time):
            self.cpu_time = t
            self.cpu_tick()

        if self.audio_wait <= (t - self._audio_time):
            self.audio_time = t
            self.sound_timer_register -= 1 if self.sound_timer_register != 0 else 0

        if self.delay_wait <= (t - self._delay_time):
            self.delay_time = t
            self.delay_timer_register -= 1 if self.delay_timer_register != 0 else 0

    def cpu_tick(self):
        '''
        Ticks the CPU forward a cycle without regard for the target frequency.
        '''
        # Handle the ld reg,k instruction
        if self.waiting_for_key:
            self.handle_load_key()
            return
        else:
            self.prev_keypad = self.decode_keypad()

        self.calling_pc = self.program_counter

        # Disassemble next instruction
        self.dis_ins = None
        try:
            self.dis_ins = self.disassemble(self.ram[self.program_counter:self.program_counter+Emulator.OP_CODE_SIZE])
        except:
            raise

        # Execute instruction
        if self.dis_ins.valid:
            self.ins_tbl[self.dis_ins.mnemonic](self)
        else:
            raise InvalidInstructionError(self.dis_ins)

        # Increment the PC
        self.program_counter += 2

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # Helpers for Load Key

    def decode_keypad(self):
        '''
        Helper method to decode the current keypad into a binary string
        '''
        return int(''.join(['1' if x else '0' for x in self.keypad]),2)

    def handle_load_key(self):
        '''
        Helper method to check if keys have changed and, if so, load the
        key per the ld reg,k instruction.
        '''
        k = self.decode_keypad()
        nk = bin( (k ^ self.prev_keypad) & k )[2:].zfill(16).find('1')
        if nk != -1:
            self.register[ get_reg1(self) ] = nk
            self.program_counter += 2
            self.waiting_for_key = False

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # Dissassembler

    @staticmethod
    def disassemble(byte_list):
        '''
        A one line (2 byte) dissassembler function for CHIP-8 Rom. It
        returns a named tuple with various information on the line.
        '''
        class EarlyExit(Exception):
            pass

        hex_instruction =  hex( byte_list[0] )[2:].zfill(2) + hex( byte_list[1] )[2:].zfill(2)
        valid = False
        mnemonic = None
        mnemonic_arg_types = None
        disassembled_line = ""
        unoffical_op = False
        banned = False
        super8 = False

        try:
            # Check if the Op-Code a Super-8 instruction
            if hex_instruction in Emulator.SUPER_CHIP_OP_CODES_EXPLODED:
                mnemonic = 'SPR'
                super8 = True
                raise EarlyExit

            # Match the instruction via a regex index
            for instruction in OP_CODES:
                _mnemonic = instruction[0]
                reg_patterns = instruction[1]
                if type(reg_patterns[0]) is not tuple:
                    reg_patterns = (reg_patterns,)
                for pattern_version in reg_patterns:
                    if not pattern_version or not match(pattern_version[0], hex_instruction):
                        continue
                    mnemonic = _mnemonic
                    mnemonic_arg_types = pattern_version[1]
                    valid = True
                    break
                if valid:
                    break

            # If not a valid instruction, assume data
            if not valid:
                disassembled_line = hex_instruction
                raise EarlyExit

            # If banned, flag and exit.
            if hex_instruction in Emulator.BANNED_OP_CODES_EXPLODED:
                banned = True
                raise EarlyExit

            # If unoffical, flag it.
            if mnemonic in Emulator.UNOFFICIAL_OP_CODES:
                unoffical_op = True

            # No args to parse
            if mnemonic_arg_types is None:
                disassembled_line = mnemonic
                raise EarlyExit

            # Parse Args
            tmp = ''
            reg_numb = 1
            for arg_type in mnemonic_arg_types:
                if arg_type is 'reg':
                    tmp = 'v'+hex_instruction[reg_numb]
                elif arg_type is 'byte':
                    tmp = '#'+hex_instruction[2:]
                elif arg_type is 'addr':
                    tmp = '#'+hex_instruction[1:]
                elif arg_type is 'nibble':
                    tmp = '#'+hex_instruction[3]
                else:
                    tmp = arg_type
                disassembled_line += tmp.ljust(5) + ','
                reg_numb = 2

            disassembled_line = (mnemonic.ljust(5) + disassembled_line[:-1]).rstrip()
        except EarlyExit:
            pass
        except:
            raise
        finally:
            return ASMdata(hex_instruction, valid, mnemonic,
                mnemonic_arg_types, disassembled_line, unoffical_op,
                banned, super8)


# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Instructions - All 20 mnemonics, 35 total instructions
# Add-3 SE-2 SNE-2 LD-11 JP-2 (mnemonics w/ extra instructions)

def i_cls(emu):
    emu.ram[Emulator.GFX_ADDRESS:Emulator.GFX_ADDRESS + Emulator.GFX_RESOLUTION] = [0x00] * Emulator.GFX_RESOLUTION
    emu.draw_flag = True

def i_ret(emu):
    emu.stack_pointer -= 1
    if emu.stack_pointer < 0:
        raise StackUnderflowError
    emu.program_counter = emu.stack.pop()

def i_sys(emu):
    pass

def i_call(emu):
    if Emulator.STACK_ADDRESS:
        emu.ram[stack_pointer] = emu.program_counter
    emu.stack_pointer += 1
    emu.stack.append(emu.program_counter)
    if emu.stack_pointer > Emulator.STACK_SIZE:
        raise StackOverflowError
    emu.program_counter = get_address(emu) - 2

def i_skp(emu):
    if emu.keypad[ get_reg1_val(emu) & 0x0F ]:
        emu.program_counter += 2

def i_sknp(emu):
    if not emu.keypad[ get_reg1_val(emu) & 0x0F ]:
        emu.program_counter += 2

def i_se(emu):
    comp = get_lower_byte(emu) if 'byte' is emu.dis_ins.mnemonic_arg_types[1] else get_reg2_val(emu)
    if get_reg1_val(emu) == comp:
        emu.program_counter += 2

def i_sne(emu):
    comp = get_lower_byte(emu) if 'byte' is emu.dis_ins.mnemonic_arg_types[1] else get_reg2_val(emu)
    if get_reg1_val(emu) != comp:
        emu.program_counter += 2

def i_shl(emu):
    if Emulator.ENABLE_LEGACY_SHIFT:
        emu.register[0xF] = 0x01 if get_reg2_val(emu) >= 0x80 else 0x0
        emu.register[ get_reg1(emu) ] = ( get_reg2_val(emu) << 1 ) & 0xFF
    else:
        emu.register[0xF] = 0x01 if get_reg1_val(emu) >= 0x80 else 0x0
        emu.register[ get_reg1(emu) ] = ( get_reg1_val(emu) << 1 ) & 0xFF

def i_shr(emu):
    if Emulator.ENABLE_LEGACY_SHIFT:
        emu.register[0xF] = 0x01 if ( get_reg2_val(emu) % 2) == 1 else 0x0
        emu.register[ get_reg1(emu) ] = get_reg2_val(emu) >> 1
    else:
        emu.register[0xF] = 0x01 if ( get_reg1_val(emu) % 2) == 1 else 0x0
        emu.register[ get_reg1(emu) ] = get_reg1_val(emu) >> 1

def i_or(emu):
    emu.register[ get_reg1(emu) ] = get_reg1_val(emu) | get_reg2_val(emu)

def i_and(emu):
    emu.register[ get_reg1(emu) ] = get_reg1_val(emu) & get_reg2_val(emu)

def i_xor(emu):
    emu.register[ get_reg1(emu) ] = get_reg1_val(emu) ^ get_reg2_val(emu)

def i_sub(emu):
    emu.register[0xF] = 0x01 if get_reg1_val(emu) >= get_reg2_val(emu) else 0x00
    emu.register[ get_reg1(emu) ] = get_reg1_val(emu) - get_reg2_val(emu)
    emu.register[ get_reg1(emu) ] &= 0xFF

def i_subn(emu):
    emu.register[0xF] = 0x01 if get_reg2_val(emu) >= get_reg1_val(emu) else 0x00
    emu.register[ get_reg1(emu) ] = get_reg2_val(emu) - get_reg1_val(emu)
    emu.register[ get_reg1(emu) ] &= 0xFF

def i_jp(emu):
    init_pc = emu.program_counter
    numb_args = len(emu.dis_ins.mnemonic_arg_types)

    if 'v0' is emu.dis_ins.mnemonic_arg_types[0] and numb_args == 2:
        emu.program_counter = get_address(emu) + emu.register[0] - 2
    elif numb_args == 1:
        emu.program_counter = get_address(emu) - 2

    if init_pc == emu.program_counter + 2:
        emu.spinning = True

def i_rnd(emu):
    emu.register[ get_reg1(emu) ] = randint(0, 255) & get_lower_byte(emu)

def i_add(emu):
    arg1 = emu.dis_ins.mnemonic_arg_types[0]
    arg2 = emu.dis_ins.mnemonic_arg_types[1]

    if 'reg' is arg1:

        if 'byte' is arg2:
            emu.register[ get_reg1(emu) ] = get_reg1_val(emu) + get_lower_byte(emu)
            emu.register[ get_reg1(emu) ] &= 0xFF
        elif 'reg' is arg2:
            emu.register[ get_reg1(emu) ] = get_reg1_val(emu) + get_reg2_val(emu)
            emu.register[0xF] = 0x01 if emu.register[ get_reg1(emu) ] > 0xFF else 0x00
            emu.register[ get_reg1(emu) ] &= 0xFF

    elif 'i' in arg1 and 'reg' is arg2:
        emu.index_register += get_reg1_val(emu)
        if (emu.index_register > 0xFF) and Emulator.SET_VF_ON_GFX_OVERFLOW:
            emu.register[0xF] = 0x01
        emu.index_register &= 0xFFF

def i_ld(emu):
    arg1 = emu.dis_ins.mnemonic_arg_types[0]
    arg2 = emu.dis_ins.mnemonic_arg_types[1]

    if 'reg' is arg1:
        if   'byte'     is arg2:
            emu.register[ get_reg1(emu) ] = get_lower_byte(emu)
        elif 'reg' is arg2:
            emu.register[ get_reg1(emu) ] = get_reg2_val(emu)
        elif 'dt'       is arg2:
            emu.register[ get_reg1(emu) ] = emu.delay_timer_register
        elif 'k'        is arg2:
            emu.waiting_for_key = True
            emu.program_counter -= 2
        elif '[i]' == arg2:
            emu.register[0: get_reg1(emu) + 1] = emu.ram[ emu.index_register : emu.index_register + get_reg1(emu) + 1]

    elif 'reg' is arg2:
        if   'dt' is arg1:
            emu.delay_timer_register =  get_reg1_val(emu)
        elif 'st' is arg1:
            emu.sound_timer_register =  get_reg1_val(emu)
        elif 'f'  is arg1:
            emu.index_register = Emulator.GFX_FONT_ADDRESS + ( 5 * get_reg1_val(emu) )
        elif 'b'  is arg1:
            bcd = [int(f) for f in list(str( get_reg1_val(emu) ).zfill(3))]
            emu.ram[ emu.index_register : emu.index_register + len(bcd)] = bcd
        elif '[i]' == arg1:
            emu.ram[ emu.index_register : emu.index_register + get_reg1(emu) + 1] = emu.register[0: get_reg1(emu) + 1]

    elif 'i' is arg1 and 'addr' is arg2:
        emu.index_register =  get_address(emu)

def i_drw(emu):
    emu.draw_flag = True
    height = int(emu.dis_ins.hex_instruction[3],16)
    x_origin_byte = int( get_reg1_val(emu) / 8 ) % Emulator.GFX_WIDTH
    y_origin_byte = (get_reg2_val(emu) % Emulator.GFX_HEIGHT_PX) * Emulator.GFX_WIDTH
    shift_amount = get_reg1_val(emu) % Emulator.GFX_WIDTH_PX % 8
    next_byte_offset = 1 if x_origin_byte + 1 != Emulator.GFX_WIDTH else 1-Emulator.GFX_WIDTH

    emu.register[0xF] = 0x00
    for y in range(height):
        sprite =  emu.ram[ emu.index_register + y ] << (8-shift_amount)

        working_bytes = (
            Emulator.GFX_ADDRESS + (( x_origin_byte + y_origin_byte + (y * Emulator.GFX_WIDTH) ) % Emulator.GFX_RESOLUTION) ,
            Emulator.GFX_ADDRESS + (( x_origin_byte + y_origin_byte + (y * Emulator.GFX_WIDTH) + next_byte_offset ) % Emulator.GFX_RESOLUTION)
        )

        original = ( emu.ram[ working_bytes[0] ], emu.ram[ working_bytes[1] ] )
        xor = (original[0]*256 + original[1]) ^ sprite
        emu.ram[ working_bytes[0] ], emu.ram[ working_bytes[1] ] = xor >> 8, xor & 0x00FF

        if (bin( ( emu.ram[ working_bytes[0] ] ^ original[0] ) & original[0] ) + \
            bin( ( emu.ram[ working_bytes[1] ] ^ original[1] ) & original[1] )).find('1') != -1:
            emu.register[0xF] = 0x01

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Hex Extraction

get_address    = lambda emu : int(emu.dis_ins.hex_instruction[1:4], 16)
get_reg1       = lambda emu : int(emu.dis_ins.hex_instruction[1],16)
get_reg2       = lambda emu : int(emu.dis_ins.hex_instruction[2],16)
get_reg1_val   = lambda emu : emu.register[int(emu.dis_ins.hex_instruction[1],16)]
get_reg2_val   = lambda emu : emu.register[int(emu.dis_ins.hex_instruction[2],16)]
get_lower_byte = lambda emu : int(emu.dis_ins.hex_instruction[2:4], 16)

