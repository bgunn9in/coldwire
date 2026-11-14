#!/usr/bin/env python3
"""Add the lab notification hook to an exact, clean pinned AWG source tree."""
import argparse
import subprocess
from pathlib import Path

PIN='1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1'

def patch(source):
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==PIN
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True).strip(), 'Use a clean source checkout'
    receive=source/'device/receive.go';text=receive.read_text()
    first='\t\t\t\tdevice.log.Verbosef("%v - Receiving keepalive packet", peer)'
    second='\t\t\tbufs = append(bufs, elem.buffer[int(elem.padding):int(elem.padding)+MessageTransportHeaderSize+len(elem.packet)])'
    assert text.count(first)==text.count(second)==1
    text=text.replace(first,'\t\t\t\tpeer.coldwireProof(elem.endpoint, elem.counter)\n'+first)
    text=text.replace(second,'\t\t\tpeer.coldwireProof(elem.endpoint, elem.counter)\n'+second)
    peer=source/'device/peer.go';old=peer.read_text();marker='type Peer struct {\n'
    assert old.count(marker)==1
    receive.write_text(text,encoding='utf-8',newline='\n')
    peer.write_text(old.replace(marker,marker+'\tcoldwireProofLast int64\n\tcoldwireProofEndpoint string\n'),encoding='utf-8',newline='\n')
    for name in ('coldwire_proof_linux.go','coldwire_proof_linux_test.go'):
        (source/'device'/name).write_bytes(Path(__file__).with_name(name).read_bytes())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);args=parser.parse_args();patch(args.source.resolve(strict=True))
