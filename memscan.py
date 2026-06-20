#!/usr/bin/env python3
"""Cheat-Engine-style differential memory scanner for a running process.

Reads /proc/<pid>/mem over writable regions (ptrace_scope=0 lets a same-user
process do this with no gdb/sudo). Usage:

    memscan.py find  <pid> <value>     # first pass: record all addresses == value
    memscan.py keep  <pid> <value>     # narrow: keep only candidates now == value
    memscan.py read  <pid>             # dump current value at each candidate
    memscan.py dump  <pid> <addr> <n>  # hex+ascii dump n bytes around addr

Tracks widths u32, i32, f32, f64 simultaneously. State in /tmp/memscan_state.json.
"""

import json
import struct
import sys

STATE = '/tmp/memscan_state.json'
WIDTHS = {'u32': ('<I', 4), 'f32': ('<f', 4), 'f64': ('<d', 8)}


def load_state():
    with open(STATE) as f:
        return json.load(f)


def save_state(pid, cand):
    with open(STATE, 'w') as f:
        json.dump({'pid': pid, 'cand': cand}, f)


def regions(pid):
    out = []
    with open(f'/proc/{pid}/maps') as f:
        for line in f:
            parts = line.split()
            if len(parts) < 5:
                continue
            addrs, perms = parts[0], parts[1]
            if 'r' not in perms or 'w' not in perms:
                continue
            path = parts[5] if len(parts) > 5 else ''
            if path in ('[vvar]', '[vdso]', '[vsyscall]'):
                continue
            lo, hi = (int(x, 16) for x in addrs.split('-'))
            out.append((lo, hi))
    return out


def packed_targets(value):
    t = {}
    iv = int(value)
    t['u32'] = struct.pack('<I', iv & 0xFFFFFFFF)
    t['f32'] = struct.pack('<f', float(value))
    t['f64'] = struct.pack('<d', float(value))
    return t


def find(pid, value):
    tgts = packed_targets(value)
    found = {w: [] for w in tgts}
    with open(f'/proc/{pid}/mem', 'rb', 0) as mem:
        for lo, hi in regions(pid):
            try:
                mem.seek(lo)
                buf = mem.read(hi - lo)
            except (OSError, ValueError, OverflowError):
                continue
            for w, tb in tgts.items():
                start = 0
                while True:
                    i = buf.find(tb, start)
                    if i < 0:
                        break
                    found[w].append(lo + i)
                    start = i + 1
    save_state(pid, found)
    print(f'value={value}: ' + ', '.join(f'{w}={len(found[w])}' for w in found))


def read_at(mem, addr, n):
    try:
        mem.seek(addr)
        return mem.read(n)
    except (OSError, ValueError, OverflowError):
        return None


def keep(pid, value):
    st = load_state()
    tgts = packed_targets(value)
    kept = {}
    with open(f'/proc/{pid}/mem', 'rb', 0) as mem:
        for w, addrs in st['cand'].items():
            _, sz = WIDTHS[w]
            tb = tgts[w]
            kk = [a for a in addrs if read_at(mem, a, sz) == tb]
            kept[w] = kk
    save_state(pid, kept)
    print(f'value={value}: ' + ', '.join(f'{w}={len(kept[w])}' for w in kept))
    for w, addrs in kept.items():
        if 0 < len(addrs) <= 12:
            print(f'  {w}: ' + ', '.join(hex(a) for a in addrs))


def read(pid):
    st = load_state()
    with open(f'/proc/{pid}/mem', 'rb', 0) as mem:
        for w, addrs in st['cand'].items():
            fmt, sz = WIDTHS[w]
            for a in addrs[:40]:
                b = read_at(mem, a, sz)
                v = struct.unpack(fmt, b)[0] if b else '?'
                print(f'  {w} {hex(a)} = {v}')


def dump(pid, addr, n):
    addr = int(addr, 0)
    n = int(n)
    with open(f'/proc/{pid}/mem', 'rb', 0) as mem:
        b = read_at(mem, addr - (addr % 16), n)
    if not b:
        print('unreadable')
        return
    base = addr - (addr % 16)
    for i in range(0, len(b), 16):
        ch = b[i : i + 16]
        asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in ch)
        print(f'{base + i:#014x} {ch.hex():<32} {asc}')


if __name__ == '__main__':
    cmd = sys.argv[1]
    pid = sys.argv[2]
    if cmd == 'find':
        find(pid, sys.argv[3])
    elif cmd == 'keep':
        keep(pid, sys.argv[3])
    elif cmd == 'read':
        read(pid)
    elif cmd == 'dump':
        dump(pid, sys.argv[3], sys.argv[4])
