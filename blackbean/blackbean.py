#!/usr/bin/python3

import os
import sys
import argparse
import tokenized_line as tzdl
from assembler_constants import *


# Issues:
#   No support for "$" notation

#Opcode reminders: SHR, SHL, XOR, and SUBN/SM are NOT offically supported by original spec
#                  SHR and SHL may or may not move Y (Shifted) into X or just shift X.

#TODO check if memory overflow
#TODO don't allow modifying VF
#TODO Use the "enfore" flag

class blackbean:
    """
    Blackbean is an assembler class that can take file handlers,
    assemble the contents, and return a stripped (comment free),
    listing, or binary file.
    """

    def __init__(self):
        """
        Init the token collection and memory map.
        Memory addresses start at 0x0200 on the CHIP 8.
        """
        self.collection = []
        self.mmap       = {}
        self.address    = 0x0200

    def reset(self):
        """
        Reset the blackbean to assemble another file.
        """
        __init__()

    def assemble(self, file_handler):
        """
        Assemble a file. Tokenizes, calculates memory addreses, and
        translates mnemonic instructions into hex.
        """
        # Pass One, Tokenize and Address
        for i,line in enumerate(file_handler):
            t = tzdl.tokenized_line(line, i)
            self.collection.append(t)
            if t.is_empty: continue
            self.calc_mem_address(t)
            
        # Pass Two, decode mnemonics
        for t in self.collection:
            if t.is_empty: continue
            self.calc_opcode(t)
            self.calc_data_declares(t)

    def print_listing(self, file_handler):
        """
        Prints a the orignal file with two additonal column, the first
        being the memory address of the first byte of the line and the
        second being the calculated hex value for the mnemonic on the
        line. Data declarations do not have their calculated hex 
        values shown as they may take more than the normal two bytes
        for all other assembler instructions.
        """
        if not self.collection:
            #TODO raise error
            Print("ERROR: Nothing to print.")
            return
        
        for line in self.collection:
            if line.instruction_int:
                form_line = format(line.mem_address, '#06x') + (4*' ') +\
                            format(line.instruction_int, '#06x') + (4*' ') +\
                            line.original
            elif line.dd_ints:
                form_line = format(line.mem_address, '#06x') + (14*' ') +\
                            line.original
            else:
                form_line = (20*' ') + line.original
            if file_handler:
                file_handler.write(form_line)
            else:
                print(form_line, end='')

    def print_strip(self, file_handler):
        """
        Prints a copy of the input file with all comments and white
        space lines removed. Useful for CHIP 8 interpreters. 
        """
        if not self.collection:
            #TODO rasie error
            Print("ERROR: Nothing to print.")
            return
        
        for line in self.collection:
            if line.is_empty:
                continue
            if file_handler:
                file_handler.write(line.original.split(BEGIN_COMMENT)[0].rstrip() + '\n')
            else:
                print(line.original.split(BEGIN_COMMENT)[0].rstrip(), end='')

    def export_binary(self, file_path):
        """
        Writes the assembled file to a binary blob. 
        """
        if not self.collection:
            #TODO rasie error
            Print("ERROR: Nothing to export.")
            return
        
        for line in self.collection:
            if line.is_empty:
                continue
            if line.instruction_int:
                file_path.write(line.instruction_int.to_bytes(OP_CODE_SIZE, byteorder='big'))
            elif line.dd_ints:
                for i in range(len(line.dd_ints)):
                    file_path.write(line.dd_ints[i].to_bytes(line.data_size , byteorder='big'))

    def calc_opcode(self, tl):
        """
        Resolve mnemonics into hex string then to ints.These
        can be easily written out. All instructions are 2 bytes.
        """
        # Skip empty lines
        if not tl.instruction:
            return
        
        for VERSION in OP_CODES[tl.instruction]:
            issue = False
            
            # Skips versions of the OPCODE that can't work
            if len(VERSION[OP_ARGS]) != len(tl.arguments):
                continue
            
            # Easy matches
            if len(VERSION[OP_ARGS]) == 0:
                tl.instruction_int = int(VERSION[OP_HEX], 16)
                break
            
            tmp = VERSION[OP_HEX]
            for i, ARG_TYPE in enumerate(VERSION[OP_ARGS]):
                tmp = is_valid_instruction_arg(ARG_TYPE, tl.arguments[i], tmp)
                if not tmp:
                    break
            
            if tmp:
                tl.instruction_int = int(tmp, 16)
                break
            
        if not tl.instruction_int:
            #TODO raise error
            print("ERROR: Unkown mnemonic-argument combination.")

    def is_valid_instruction_arg(arg_type, arg_value, hex_template):
        if arg_type == arg_value:
            return ''
        
        if arg_type is 'register' 
            if arg_value in REGISTERS:
                return hex_template.replace(ARG_SUB[i], arg_value[1])
        
        elif arg_type is 'address':
            if arg_value[0] is HEX_ESC:
                arg_value = arg_value[1:]
                if len(arg_value) == 3:
                    return hex_template.replace(ARG_SUB[i] * 3, arg_value)
            elif arg_value in self.mmap:
                return hex_template.replace(ARG_SUB[i] * 3, hex(self.mmap[arg_value])[2:])
        
        elif arg_type is 'byte':
            if arg_value[0] is HEX_ESC:
                arg_value = arg_value[1:]
            else:
                try:
                    arg_value = hex(int(arg_value))[2:].zfill(2)
                except: pass
            if len(arg_value) == 2:
                try:
                    int(arg_value, 16) # Make sure its hex
                    return hex_template.replace(ARG_SUB[i] * 2, arg_value)
                except: pass
            
        elif arg_type is 'nibble':
            if arg_value[0] is HEX_ESC:
                arg_value = arg_value[1:]
            if len(arg_value) == 1:
                try:
                    int(arg_value, 16) # Make usre its hex
                    return hex_template.replace(ARG_SUB[i], arg_value)
                except: pass
            
        return ''

    def calc_data_declares(self, tl):
        """
        Resolve data declarations on a line into list of ints. These
        can be easily written out. Size (# of bytes) was found when
        tokenizing the line.
        """
        # Skip lines w/o dd
        if not tl.data_declarations:
            return
        
        for arg in tl.data_declarations:
            
            # Try to parse the values
            if arg[0] is HEX_ESC:
                arg = arg[1:]
                if len(arg) == (2 * tl.data_size):
                    try: val = int(arg, 16)
                    except: pass
            elif arg.isdigit():
                val = int(arg)
            
            # Raise errors if parse failed or val too large
            if not val:
                #TODO raise error
                print("ERROR: Incorrectly formated data declaration.")
                break
            if val >= pow(256, tl.data_size):
                #TODO raise error
                print("ERROR: Data declaration overflow.")
                break
            
            tl.dd_ints.append(val)

    def calc_mem_address(self, tl):
        """
        Assign memory addresses to mnemonics (now packed in tokenized
        lines). Store any memory tags found in the memory map to be
        used on the second pass.
        """
        # Add any tags to the mem map
        if tl.mem_tag:
            self.mmap[tl.mem_tag] = self.address
        
        # One or the other per line, if both then errors are raised
        if tl.instruction:
            tl.mem_address = self.address
            self.address += OP_CODE_SIZE
        elif tl.data_size:
            tl.mem_address = self.address
            self.address += (len(tl.data_declarations) * tl.data_size)

def parse_args():
    """
    Parse arguments to blackbean when called as a script.
    """
    parser = argparse.ArgumentParser(description='Blackbean will assemble your CHIP-8 programs to executable machine code. BB can also generate listing files and comment-striped files. The "enforce" option is not currently supported.')
    parser.add_argument('input', help='file to assemble.')
    parser.add_argument('-o','--output',help='file to store binary executable to, by default INPUT.bin is used.')
    parser.add_argument('-l','--list',  help='generate listing file and store to OUTPUT.lst file.',action='store_true')
    parser.add_argument('-s','--strip', help='strip comments and store to OUTPUT.strip file.',action='store_true')
    parser.add_argument('-e','--enforce',help='force original Chip-8 specification and do not allow SHR, SHL, XOR, or SUBN instructions.',action='store_true')
    opts = parser.parse_args()

    if not os.path.isfile(opts.input):
        raise OSError("File '" + opts.input + "' does not exist.")
    if not opts.output:
        if opts.input.endswith('.src'):
            opts.output = opts.input[:-4]
        else:
            opts.output = opts.input

    return opts

def main(opts):
    """
    Handles blackbean being called as a script.
    """
    bb = blackbean()
    with open(opts.input) as FH:
        bb.assemble(FH)
    if opts.list:
        with open(opts.output + '.lst', 'w') as FH:
            bb.print_listing(FH)
    if opts.strip:
        with open(opts.output + '.strip', 'w') as FH:
            bb.print_strip(FH)
    if opts.input == opts.output:
        with open(opts.output + '.bin', 'w') as FH:
            bb.export_binary(FH)
    else:
        with open(opts.output, 'wb') as FH:
            bb.export_binary(FH)

if __name__ == '__main__':
    main(parse_args())


############################################################
# Below are utility functions usefull if creating a class
# is over shooting your needs.

def util_strip_comments(file_path, outpout_handler = None):
    with open(file_path) as fhandler:
        for line in fhandler:
            if line.isspace(): continue
            if line.lstrip().startswith(BEGIN_COMMENT): continue
            line = line.split(BEGIN_COMMENT)[0].rstrip()
            if outpout_handler == None:
                print(line)
            else:
                outpout_handler.write(line)

def util_add_listing(file_path, outpout_handler = None):
    mem_addr = 0x0200
    with open(file_path) as fhandler:
        for line in fhandler:
            mem_inc = 2
            nocomment = line.split(BEGIN_COMMENT)[0].rstrip().lower()
            if not nocomment or nocomment.endswith(':') or any(s in nocomment for s in PRE_PROC):
                line = (10*' ') + line
            else:
                for k in DATA_DEFINE:
                    if k in nocomment:
                        mem_inc = DATA_DEFINE[k]
                        break
                line = format(mem_addr, '#06x') + (4*' ') + line
                mem_addr += mem_inc
            if outpout_handler == None:
                print(line, end='')
            else:
                outpout_handler.write(line, end='')




