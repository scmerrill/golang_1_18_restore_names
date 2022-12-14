#!/usr/bin/env python3

import re
import struct

import binaryninja
from binaryninja.log import log_error, log_info


_RE_REPLACE_UNDERSCORE = re.compile("[^a-zA-Z0-9_]")
_RE_COMPRESS_UNDERSCORE = re.compile("__+")


def sanitize_func_name(name):
    varname = _RE_REPLACE_UNDERSCORE.sub("_", name)
    varname = _RE_COMPRESS_UNDERSCORE.sub("_", varname)
    return varname


def is_gopclntab_section(view: binaryninja.binaryview.BinaryView,
                         section: binaryninja.binaryview.Section) -> bool:

    if section.name == ".gopclntab":
        return True

    # validate magic bytes
    magic_bytes_found = view.read(section.start, 4)
    magic_bytes_expected = b'\xf0\xff\xff\xff'
    if magic_bytes_expected != magic_bytes_found:
        return False
    ptr_size = view.address_size
    first_entry = section.start + 8 + ptr_size
    first_fun_addr = get_pointer_LE(view, first_entry)
    first_entry_struct_func_offset = get_pointer_LE(view, first_entry + 8)
    fun_addr_struct_func = get_pointer_LE(view, section.start + first_entry_struct_func_offset)
    if first_fun_addr != fun_addr_struct_func:
        return False
    return True


def get_pointer_LE(view: binaryninja.binaryview.BinaryView, addr: int) -> bytes:
    addr_size = view.address_size
    return struct.unpack("<L" if addr_size == 4 else "<Q", view.read(addr, addr_size))[0]


def get_dword_LE(view: binaryninja.binaryview.BinaryView, addr: int) -> bytes:
    #log_info(f"Addr is {addr:x}")
    #log_info(f"bytes are {struct.unpack('<I', view.read(addr, 4))[0]:x}")
    return struct.unpack("<I", view.read(addr, 4))[0]


def restore_symbols(view: binaryninja.binaryview.BinaryView,
                    gopclntab: binaryninja.binaryview.Section) -> None:
    ptr_size = view.address_size

    """
    the .gopclntab table (starting at .gopclntab + 8) consists of
        N pc0 func0 pc1 func1 pc2 func2 ... pc(N-1) func(N-1) pcN
        
        N := no of elemements in table
        pcX := pointer to the function
        funcX := pointer to struct Func
        
        struct Func {
                uintptr entry;   // start pc
                int32 name;      // name (offset to C string)
                int32 args;      // size of arguments passed to function
                int32 frame;     // size of function frame, including saved caller PC
                int32 pcsp;      // pcsp table (offset to pcvalue table)
                int32 pcfile;    // pcfile table (offset to pcvalue table)
                int32 pcln;      // pcln table (offset to pcvalue table)
                int32 nfuncdata; // number of entries in funcdata list
                int32 npcdata;   // number of entries in pcdata list
        }; 
    src: https://docs.google.com/document/d/1lyPIbmsYbXnpNj57a261hgOYVpNRcgydurVQIyZOz_o/pub
    """
    # validate magic bytes
    magic_bytes_found = view.read(gopclntab.start, 4)
    magic_bytes_expected = b'\xf0\xff\xff\xff'
    if magic_bytes_expected != magic_bytes_found:
        log_error("Invalid .gopclntab section. Aborting!")
        return

    # get number of elements and calculate last address
    size_addr = gopclntab.start + 8  # skip first 8 bytes
    size = get_pointer_LE(view, size_addr)
    start_addr = size_addr + ptr_size
    end_addr = gopclntab.start + 8 + ptr_size + (size * ptr_size * 2)

    # iterate over the table and restore function names
    for current_addr in range(start_addr, end_addr, 2 * ptr_size):
        log_info(f"current_adr = 0x{current_addr:x}, start addr = 0x{start_addr:x}, end addr = 0x{end_addr:x}, ptr size = {ptr_size}")
        function_addr = get_pointer_LE(view, current_addr)
        log_info(f"func addr = {function_addr:x}")
        struct_func_offset = get_pointer_LE(view, current_addr + ptr_size)
        name_str_offset = get_dword_LE(view, (gopclntab.start + struct_func_offset + ptr_size))
        name_addr = gopclntab.start + name_str_offset
        function_name = view.get_ascii_string_at(name_addr)
        if not function_name:
            continue
        log_info(f'found name "{function_name}" for function starting at 0x{function_addr:x}')
        function = view.get_function_at(function_addr)
        if not function:
            view.create_user_function(function_addr)
            function = view.get_function_at(function_addr)

        new_func_comment = function_name.value
        if function.comment:
            new_func_comment += "\n\n{}".format(function.comment)
        function.comment = new_func_comment
        function.name = sanitize_func_name(function_name.value)


def restore_golang_symbols(view: binaryninja.binaryview.BinaryView):
    for section in view.sections.values():
        if is_gopclntab_section(view, section):
            log_info(f"found .gopclntab at 0x{section.start:x}")
            renameFunc118(view, section)
            break
    else:
        log_error("Could not find .gopclntab section. "
                  "If this is really a Golang binary you can annotate "
                  "the section manually by naming it '.gopclntab'")


#Recover function names for Go versions 1.18 and above converted from Ghidra to work with binja
def renameFunc118(view: binaryninja.binaryview.BinaryView,
                    gopclntab: binaryninja.binaryview.Section) -> None:
    ptr_size = view.address_size

    nfunctab = get_dword_LE(view, gopclntab.start + 8)
    textStart = get_dword_LE(view, gopclntab.start + 8 + 2* ptr_size)
    offset = get_dword_LE(view, gopclntab.start + 8 + 3*ptr_size)
    funcnametab = gopclntab.start + offset
    offset = get_dword_LE(view, gopclntab.start + 8 + 7*ptr_size)
   
    functab = gopclntab.start + offset

    p = functab
    functabFieldSize = 4
    for i in range (nfunctab):
        #log_info(f"func address = 0x{get_dword_LE(view, p)+textStart:x}, nfunctab = 0x{nfunctab:x}, textStart = 0x{textStart:x}")
        func_address = get_dword_LE(view, p) + textStart
        p = p + functabFieldSize
        funcdata_offset = get_dword_LE(view, p)
        p = p + functabFieldSize
        name_pointer = functab + funcdata_offset + functabFieldSize
        name_addr = funcnametab + get_dword_LE(view, name_pointer)
        #log_info(f"name addr = {name_addr:x}, name_pointer = {name_pointer:x}")
        function_name = view.get_ascii_string_at(name_addr)
        #log_info(f"function name = {function_name}")
        if not function_name:
            continue
        log_info(f'found name "{function_name}" for function starting at 0x{func_address:x}')
        function = view.get_function_at(func_address)
        if not function:
            view.create_user_function(func_address)
            function = view.get_function_at(func_address)

        new_func_comment = function_name.value
        if function.comment:
            new_func_comment += "\n\n{}".format(function.comment)
        function.comment = new_func_comment
        function.name = sanitize_func_name(function_name.value)

