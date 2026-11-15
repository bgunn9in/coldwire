import errno
import struct
import unittest
from unittest import mock
import conntrack as ct

class ConntrackTests(unittest.TestCase):
    def setUp(self):
        self.entry='192.168.76.10';self.exit='192.168.76.20';self.port=32497;self.nat=42501;self.seq=123
        self.body=b'\x02\0\0\0'+ct.attribute(0x8001,ct.tuple_bytes('192.168.76.31',self.entry,41000,self.port))+ct.attribute(0x8002,ct.tuple_bytes(self.exit,self.entry,self.port,self.nat))+ct.attribute(12,struct.pack('!I',456))+ct.attribute(3,struct.pack('!I',8))
    def message(self,body=None,kind=0x100,seq=None,flags=0):
        body=self.body if body is None else body
        return ct.HEADER.pack(16+len(body),kind,flags,self.seq if seq is None else seq,0)+body
    def parse(self,data):return ct.parse(data,self.seq,self.entry,self.exit,self.port,self.nat)
    def test_exact_reply_tuple_and_generation(self):
        self.assertEqual(self.parse(self.message()),('192.168.76.31',41000,456,self.nat))
        self.assertEqual(self.parse(self.message(flags=2)),('192.168.76.31',41000,456,self.nat))
        for value in (self.message(seq=124),self.message(flags=4),self.message(kind=0x101),self.message(self.body.replace(struct.pack('!H',self.nat),struct.pack('!H',self.nat+1))),self.message(self.body[:-4]+b'\0'*4),self.message(self.body[:20]),self.message()+b'\0'):
            with self.assertRaises(ValueError):self.parse(value)
    def test_absence_is_distinct_from_lookup_failure(self):
        self.assertIsNone(self.parse(self.message(struct.pack('=i',-errno.ENOENT),kind=2)))
        with self.assertRaises(PermissionError):self.parse(self.message(struct.pack('=i',-errno.EPERM),kind=2))
        for data in (b'',b'\0'*16,self.message(b'',kind=2),self.message(struct.pack('=i',0),kind=2)):
            with self.assertRaises(ValueError):self.parse(data)
    def test_original_tuple_uses_actual_translated_port_and_requires_ct_id(self):
        self.assertEqual(ct.parse(self.message(),self.seq,self.entry,self.exit,self.port,None,('192.168.76.31',41000),456)[3],self.nat)
        for original,identity in ((('192.168.76.30',41000),456),(('192.168.76.31',41001),456),(('192.168.76.31',41000),457)):
            with self.assertRaises(ValueError):ct.parse(self.message(),self.seq,self.entry,self.exit,self.port,None,original,identity)
    def test_attribute_boundaries_and_duplicates(self):
        for data in (b'\0',b'\0'*4,ct.attribute(1,b'a')*2,struct.pack('=HH',99,1)+b'ab',ct.attribute(1,b'a')[:-1]):
            with self.assertRaises(ValueError):ct.attributes(data)
    def test_socket_requests_get_without_dump_or_multicast(self):
        connection=mock.MagicMock();connection.__enter__.return_value=connection
        connection.sendto.side_effect=lambda data,peer:len(data)
        connection.recvmsg.return_value=(self.message(),[],0,(0,0))
        with mock.patch.object(ct.socket,'AF_NETLINK',16,create=True),mock.patch.object(ct.socket,'MSG_TRUNC',32,create=True),mock.patch.object(ct.socket,'MSG_CTRUNC',8,create=True),mock.patch.object(ct.socket,'socket',return_value=connection),mock.patch.object(ct.secrets,'randbits',return_value=self.seq):
            self.assertEqual(ct.lookup(self.entry,self.exit,self.port,self.nat)[2],456)
            data,peer=connection.sendto.call_args.args
            self.assertEqual(ct.HEADER.unpack_from(data)[1:4],(0x101,1,self.seq));self.assertEqual(peer,(0,0))
            self.assertEqual(ct.attributes(data[20:])[2],ct.tuple_bytes(self.exit,self.entry,self.port,self.nat))
            for flags,sender in ((32,(0,0)),(0,(123,0))):
                connection.recvmsg.return_value=(self.message(),[],flags,sender)
                with self.assertRaises(ValueError):ct.lookup(self.entry,self.exit,self.port,self.nat)

if __name__=='__main__':unittest.main()
