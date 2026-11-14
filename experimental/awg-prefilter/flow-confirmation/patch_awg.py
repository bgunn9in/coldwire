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
    text=text.replace(first,'\t\t\t\tpeer.coldwireProof(elem.endpoint, elem.keypair, elem.counter)\n'+first)
    text=text.replace(second,'\t\t\tpeer.coldwireProof(elem.endpoint, elem.keypair, elem.counter)\n'+second)
    text=text.replace('\t\tvalidTailPacket := -1','\t\tvalidTailPacket := -1\n\t\tendpointTailPacket := -1')
    marker_receive='\t\t\tvalidTailPacket = i\n\t\t\tif peer.ReceivedWithKeypair(elem.keypair) {\n\t\t\t\tpeer.SetEndpointFromPacket(elem.endpoint)'
    assert text.count(marker_receive)==1
    text=text.replace(marker_receive,'\t\t\tvalidTailPacket = i\n\t\t\tpromoted := peer.ReceivedWithKeypair(elem.keypair)\n\t\t\tif peer.coldwireEndpointCandidate(elem.keypair, elem.counter) { endpointTailPacket = i }\n\t\t\tif promoted {\n\t\t\t\tpeer.coldwireCommitEndpoint(elem.endpoint, elem.keypair, elem.counter)')
    tail='\t\t\tpeer.SetEndpointFromPacket(elemsContainer.elems[validTailPacket].endpoint)'
    assert text.count(tail)==1
    text=text.replace(tail,'\t\t\tif endpointTailPacket >= 0 {\n\t\t\t\telem := elemsContainer.elems[endpointTailPacket]\n\t\t\t\tpeer.coldwireCommitEndpoint(elem.endpoint, elem.keypair, elem.counter)\n\t\t\t}')
    peer=source/'device/peer.go';old=peer.read_text();marker='type Peer struct {\n'
    assert old.count(marker)==1
    receive.write_text(text,encoding='utf-8',newline='\n')
    peer.write_text(old.replace(marker,marker+'\tcoldwireProofLast int64\n\tcoldwireProofEndpoint string\n\tcoldwireEndpointBirth time.Time\n\tcoldwireEndpointIndex uint32\n\tcoldwireEndpointCounter uint64\n\tcoldwireReturnLast time.Time\n'),encoding='utf-8',newline='\n')
    send=source/'device/send.go';outbound=send.read_text();marker_send='\t\t\t\tdataSent = true'
    assert outbound.count(marker_send)==1
    send.write_text(outbound.replace(marker_send,marker_send+'\n\t\t\t\tpeer.coldwireRememberReply(elem.packet, elem.keypair)'),encoding='utf-8',newline='\n')
    for name in ('coldwire_proof_linux.go','coldwire_proof_linux_test.go','coldwire_return_linux.go','coldwire_return_linux_test.go','coldwire_return_boundary_linux_test.go','coldwire_return_deferred_linux.go','coldwire_return_deferred_linux_test.go'):
        (source/'device'/name).write_bytes(Path(__file__).with_name(name).read_bytes())

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);args=parser.parse_args();patch(args.source.resolve(strict=True))
