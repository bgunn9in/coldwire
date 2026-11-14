"""Decode actual verdict datagrams: class metadata must never change payload or IDs."""
import os
from pathlib import Path
import struct
import subprocess
import unittest
import test_prefilter as f

DRIVER=Path(os.environ.get('PREFILTER_BATCH_DRIVER',str(f.HERE/'test-batch-handshake'))).resolve()

class HandshakeMarks(unittest.TestCase):
    setUp=f.PrefilterTests.setUp
    tearDown=f.PrefilterTests.tearDown
    def run_frames(self,types,mode='',expected=0):
        records=[]
        for i,kind in enumerate(types):
            packet=f.packet(bytes.fromhex(f.VECTORS[str(abs(kind))]))
            if kind<0:
                packet=bytearray(packet);packet[58]^=1;packet=bytes(packet)
            records.append(((0xfffffffd+i)&0xffffffff,kind,packet))
        data=b''.join(struct.pack('!III',n,len(p),min(212,len(p)))+p[:212] for n,_,p in records)
        out=subprocess.run([str(DRIVER),str(self.key)],input=data,capture_output=True,env=dict(os.environ,BATCH_TEST_MARK='0xa0000002',BATCH_TEST_SEND=mode))
        self.assertEqual(out.returncode,expected,out.stderr.decode(errors='replace'))
        decoded=[]
        for line in out.stdout.splitlines():
            wire=bytes.fromhex(line.decode())
            while wire:
                length,type_,flags,sequence,pid=struct.unpack_from('=IHHII',wire)
                self.assertEqual((length,type_,flags),(40,769,1))
                self.assertEqual(struct.unpack_from('!BBH',wire,16),(0,0,100))
                self.assertEqual(struct.unpack_from('=HH',wire,20),(12,2))
                verdict,n=struct.unpack_from('!II',wire,24)
                self.assertEqual(struct.unpack_from('=HH',wire,32),(8,3))
                mark=struct.unpack_from('!I',wire,36)[0]
                decoded.append((n,verdict,mark));wire=wire[length:]
        return records,decoded
    def test_types_marks_id_wrap_and_original_mark_bits(self):
        records,decoded=self.run_frames([1,2,3,4,-1,-2]*6)
        self.assertEqual(decoded,[(n,int(k>0),0xe0000002 if k in (1,2,3) else 0xc0000002) for n,k,_ in records])
    def test_interrupted_send_retains_same_marks(self):
        records,decoded=self.run_frames([4,1,2,-1],mode='eintr')
        self.assertEqual(decoded,[(n,int(k>0),0xe0000002 if k in (1,2,3) else 0xc0000002) for n,k,_ in records])
    def test_failed_send_never_releases_packets(self):
        _,decoded=self.run_frames([1,4],mode='failure',expected=1);self.assertEqual(decoded,[])

if __name__=='__main__':unittest.main()
