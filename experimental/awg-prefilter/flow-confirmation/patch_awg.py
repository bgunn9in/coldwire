#!/usr/bin/env python3
"""Patch the pinned Linux AWG receiver for lab proof and recovery."""
import argparse
import re
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
    peer.write_text(old.replace(marker,marker+'\tcoldwireProofLast int64\n\tcoldwireProofEndpoint string\n\tcoldwireAdmissionLast int64\n\tcoldwireAdmissionEndpoint string\n\tcoldwireEndpointBirth time.Time\n\tcoldwireEndpointIndex uint32\n\tcoldwireEndpointCounter uint64\n\tcoldwireReturnMu sync.Mutex\n\tcoldwireReturnLast time.Time\n'),encoding='utf-8',newline='\n')
    send=source/'device/send.go';outbound=send.read_text();marker_send='\t\t\t\tdataSent = true'
    assert outbound.count(marker_send)==1
    send.write_text(outbound.replace(marker_send,marker_send+'\n\t\t\t\tpeer.coldwireRememberReply(elem.packet, elem.keypair)'),encoding='utf-8',newline='\n')
    # Only B's receiver gets extra reordering headroom; client replay tests keep the upstream window.
    replay=(source/'replay/replay.go').read_text()
    assert replay.count('package replay')==replay.count('ringBlocks  = 1 << 7')==1
    replay=replay.replace('package replay','package device').replace('ringBlocks  = 1 << 7','ringBlocks  = 1 << 8')
    names=('Filter','block','blockBitLog','blockBits','ringBlocks','windowSize','blockMask','bitMask')
    replay=re.sub(r'\b('+ '|'.join(names) +r')\b',lambda m:'coldwireReplay'+m[0][0].upper()+m[0][1:],replay)
    (source/'device/coldwire_replay_linux.go').write_text(replay,encoding='utf-8',newline='\n')
    keypair=source/'device/keypair.go';keys=keypair.read_text()
    assert keys.count('replay.Filter')==1
    keys=keys.replace('replay.Filter','coldwireReplayFilter')
    keys=keys.replace('\t"github.com/amnezia-vpn/amneziawg-go/v3/replay"\n','')
    keypair.write_text(keys,encoding='utf-8',newline='\n')
    copied=('coldwire_proof_linux.go','coldwire_proof_linux_test.go','coldwire_return_linux.go','coldwire_return_linux_test.go','coldwire_return_boundary_linux_test.go','coldwire_return_deferred_linux.go','coldwire_return_deferred_linux_test.go','coldwire_replay_linux_test.go')
    for name in copied:
        (source/'device'/name).write_bytes(Path(__file__).with_name(name).read_bytes())
    subprocess.run(['gofmt','-w',*[str(source/'device'/name) for name in ('receive.go','peer.go','send.go','keypair.go','coldwire_replay_linux.go',*copied)]],check=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);args=parser.parse_args();patch(args.source.resolve(strict=True))
