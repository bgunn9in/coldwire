import importlib.util
from pathlib import Path
import struct
import sys
import unittest

spec=importlib.util.spec_from_file_location('flow_agent',Path(__file__).with_name('agent.py'))
agent=importlib.util.module_from_spec(spec);sys.modules[spec.name]=agent;spec.loader.exec_module(agent)

class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.flow=agent.Flow('192.168.76.30',32497,123,32497)
        self.entry=agent.Entry();self.exit=agent.Exit('192.168.76.10')
    def event(self,stamp,port=32497):
        return agent.EVENT.pack(b'CWP1',stamp,bytes([192,168,76,10]),port,bytes.fromhex('ab'*16),42)
    def test_new_authenticated_event_required(self):
        query=self.entry.queries({self.flow},10)[0];self.exit.query(query,10.1)
        self.assertEqual(self.exit.event(self.event(10000000000),10.2),[])
        proof=self.exit.event(self.event(10200000000),10.3)[0]
        self.assertTrue(self.entry.confirm(proof,{self.flow},10.4))
        self.assertEqual(self.entry.leases[self.flow][1],20.4)
        self.assertFalse(self.entry.confirm(proof,{self.flow},10.5))
    def test_nat_port_reuse_and_flow_generation(self):
        query=self.entry.queries({self.flow},10)[0];self.exit.query(query,10.1)
        proof=self.exit.event(self.event(10200000000),10.3)[0]
        replacement=agent.Flow('192.168.76.40',40000,124,32497)
        self.assertFalse(self.entry.confirm(proof,{replacement},10.4))
        self.assertFalse(self.entry.leases)
        query2=self.entry.queries({replacement},10.5)[0]
        self.assertNotEqual(query2['nonce'],query['nonce'])
        self.assertFalse(self.entry.confirm(proof,{replacement},10.6))
    def test_peer_move_and_old_proof_order(self):
        query=self.entry.queries({self.flow},1)[0]
        first={'nonce':query['nonce'],'peer':'ab'*16,'stamp':100}
        self.assertTrue(self.entry.confirm(first,{self.flow},1.1))
        moved=agent.Flow('192.168.76.31',42501,456,42501)
        query2=self.entry.queries({self.flow,moved},2)[0]
        self.assertEqual(self.entry.pending[query2['nonce']][0],moved)
        self.assertTrue(self.entry.confirm({'nonce':query2['nonce'],'peer':'ab'*16,'stamp':200},{self.flow,moved},2.1))
        self.assertEqual(set(self.entry.leases),{moved})
        query3=self.entry.queries({self.flow,moved},4)[0]
        self.assertFalse(self.entry.confirm({'nonce':query3['nonce'],'peer':'ab'*16,'stamp':150},{self.flow,moved},4.1))
    def test_expiry_limits_and_unrelated_events(self):
        query=self.entry.queries({self.flow},1)[0];self.exit.query(query,1)
        self.assertEqual(self.exit.event(self.event(1100000000,40000),1.2),[])
        self.assertEqual(self.exit.event(b'bad',1.2),[])
        self.assertEqual(self.exit.event(self.event(5000000000),1.2),[])
        self.assertEqual(self.exit.event(self.event(1100000000),5),[])
        self.assertFalse(self.entry.confirm({'nonce':query['nonce'],'peer':'ab'*16,'stamp':2},{self.flow},5))
        for value in ({'nonce':'ab'*16,'port':True},{'nonce':'bad','port':32497},{'nonce':'ab'*16,'port':0},{'nonce':'ab'*16,'port':65536}):self.exit.query(value,10)
        self.assertFalse(self.exit.pending)
        self.entry.leases[self.flow]=('ab'*16,11)
        self.entry.queries({self.flow},12);self.assertFalse(self.entry.leases)
        large={agent.Flow('192.168.76.40',40000+i,i+1,40000+i) for i in range(256)}
        self.assertEqual(len(self.entry.queries(large,20)),16)
    def test_conntrack_mapping_and_input_validation(self):
        text='udp 17 180 src=192.168.76.30 dst=192.168.76.10 sport=32497 dport=32497 src=192.168.76.20 dst=192.168.76.10 sport=32497 dport=32497 [ASSURED] mark=0 use=1 id=123\n'
        self.assertEqual(agent.parse_conntrack(text,'192.168.76.10','192.168.76.20',32497),{self.flow})
        self.assertEqual(agent.parse_conntrack(text.replace('id=123','id=0'),'192.168.76.10','192.168.76.20',32497),set())
        self.assertEqual(agent.parse_conntrack(text.replace('sport=32497 dport=32497 [ASSURED]','sport=123 dport=32497 [ASSURED]'),'192.168.76.10','192.168.76.20',32497),set())
        self.assertEqual(agent.parse_conntrack('unrelated','192.168.76.10','192.168.76.20',32497),set())
    def test_nanosecond_cutoff_and_buffered_TLS_records(self):
        request={'nonce':'cd'*16,'port':32497}
        self.exit.query(request,10,cutoff_ns=10000000123)
        self.assertEqual(self.exit.event(self.event(10000000122),10.1),[])
        self.assertEqual(len(self.exit.event(self.event(10000000124),10.1)),1)
        class BufferedTLS:
            def __init__(self):self.blocks=[b'{"n":1}\n',b'{"n":2}\n']
            def setblocking(self,value):pass
            def recv(self,size):
                if self.blocks:return self.blocks.pop(0)
                raise agent.ssl.SSLWantReadError()
        self.assertEqual(agent.Stream(BufferedTLS()).read(),[{'n':1},{'n':2}])

if __name__=='__main__':unittest.main()
