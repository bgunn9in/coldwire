# SPDX-License-Identifier: MIT
import ipaddress,stat,struct,types,unittest
from unittest import mock
import agent
class EarlyProbeTests(unittest.TestCase):
    def setUp(self):self.f=agent.Flow('192.168.76.31',42501,123,55000);self.s=agent.Entry(agent.ESCROW_SOCKET)
    def test_one_early_after_write_then_one_fallback_after_ready(self):
        n=self.s.queries({self.f},10)[0]['nonce'];self.assertEqual(self.s.probes({self.f},10),[])
        self.s.sent.add(n);self.assertEqual(self.s.probes({self.f},10.1),[(n,self.f)])
        self.s.early_probed.add(n);self.assertEqual(self.s.probes({self.f},10.2),[]);self.assertFalse(self.s.leases)
        self.assertTrue(self.s.acknowledged({'ready':n},10.3));self.assertEqual(self.s.probes({self.f},10.3),[(n,self.f)])
        self.s.probed.add(n);self.assertEqual(self.s.probes({self.f},10.4),[])
        self.s.queries(set(),14);self.assertFalse(self.s.sent or self.s.early_probed or self.s.probed or self.s.leases)
    def test_pre_query_packet_cannot_prove_admission(self):
        q=self.s.queries({self.f},10)[0];self.s.sent.add(q['nonce']);self.s.early_probed.add(q['nonce']);b=agent.Exit('192.168.76.10');self.assertTrue(b.query(q,10,10000000000))
        def event(stamp):return agent.EVENT.pack(b'CWP1',stamp,ipaddress.IPv4Address('192.168.76.10').packed,self.f.translated_port,b'a'*16,42)
        rows=b.event(event(9999999999),10.05);self.assertFalse(any('nonce' in r for r in rows));self.assertFalse(self.s.leases)
        rows=b.event(event(10060000000),10.07);proof=next(r for r in rows if 'nonce' in r);self.assertTrue(self.s.confirm(proof,{self.f},10.08))
        self.assertIn(self.f,self.s.leases)
    def test_session_reset_clears_write_and_early_state(self):
        q=self.s.queries({self.f},10)[0];self.s.sent.add(q['nonce']);self.s.early_probed.add(q['nonce']);self.s.new_control_session();self.assertFalse(self.s.sent or self.s.early_probed or self.s.pending)
    def test_root_encoding_and_strict_early_boolean(self):
        parent=types.SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0);endpoint=types.SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=0);con=mock.MagicMock();con.__enter__.return_value=con;sent=[];con.sendto.side_effect=lambda data,path:sent.append(data) or len(data)
        with mock.patch.object(agent.Path,'lstat',side_effect=lambda p:parent if p==agent.Path(agent.ESCROW_SOCKET).parent else endpoint,autospec=True),mock.patch.object(agent.socket,'socket',return_value=con),mock.patch.object(agent.socket,'AF_UNIX',1,create=True):
            self.assertTrue(agent.probe_escrow(self.s,self.f,10,early=True));self.assertEqual(sent[-1][:4],b'CWT1');self.assertEqual(len(sent[-1]),22)
            self.assertTrue(agent.probe_escrow(self.s,self.f,10));self.assertEqual(sent[-1][:4],b'CWS1')
            self.assertFalse(agent.probe_escrow(self.s,self.f,10,early=1));self.assertFalse(self.s.leases)
    def test_blocked_partial_and_completed_tls_writes_then_ack_fallback(self):
        state=self.s;flow=self.f;steps=[0];clock=[10.];handlers={};queries=[];connection=mock.Mock();connection.pending.return_value=0
        opening=mock.Mock(socket=connection,write=True,deadline=12);opening.advance.return_value=True
        class FakeStream:
            def __init__(self,sock):self.socket=sock;self.outgoing=bytearray()
            def queue(self,message):queries.append(message);self.outgoing.extend(b'query')
            def write(self):
                if steps[0]==3:del self.outgoing[:1]
                if steps[0]==4:self.outgoing.clear()
            def read(self):
                if steps[0]==1:return [{'hint':flow.translated_port}]
                if steps[0]==5:return [{'ready':queries[0]['nonce']}]
                if steps[0]==6:raise EOFError
                return []
        def select(readers,writers,errors,timeout):
            steps[0]+=1;clock[0]=10+(.0,.02,.12,.24,.36,.48,.49)[steps[0]-1]
            if steps[0] in (2,3,4):self.assertFalse(state.sent)
            if steps[0] in (1,2,3,4):return [],[connection],[]
            if steps[0] in (5,6):return [connection],[],[]
            handlers[agent.signal.SIGTERM]();return [],[],[]
        directory=mock.Mock(st_uid=0,st_mode=stat.S_IFDIR|0o700);candidate=mock.Mock()
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497,'status':'unused','escrow_socket':agent.ESCROW_SOCKET}
        with mock.patch.object(agent.os,'geteuid',return_value=0,create=True), \
                            mock.patch.multiple(agent.Path,read_text=mock.Mock(return_value='kit-entry'),lstat=mock.Mock(return_value=directory),exists=mock.Mock(return_value=False),chmod=mock.Mock(),unlink=mock.Mock()), \
                            mock.patch.object(agent,'context'),mock.patch.object(agent,'restore_leases'),mock.patch.object(agent,'Entry',return_value=state), \
                            mock.patch.object(agent.socket,'socket',return_value=candidate),mock.patch.multiple(agent.socket,SO_PASSCRED=16,SCM_CREDENTIALS=2,AF_UNIX=1,create=True), \
                            mock.patch.object(agent.signal,'signal',side_effect=lambda sig,fn:handlers.__setitem__(sig,fn)), \
                            mock.patch.object(agent.Handshake,'outgoing',return_value=opening),mock.patch.object(agent,'Stream',FakeStream), \
                            mock.patch.object(agent.select,'select',side_effect=select),mock.patch.object(agent.time,'monotonic',side_effect=lambda:clock[0]), \
                            mock.patch.object(agent,'read_flow',return_value=flow),mock.patch.object(agent,'install_leases'),mock.patch.object(agent,'snapshot'), \
                            mock.patch.object(agent,'notify_escrow',return_value=True),mock.patch.object(agent,'probe_escrow',return_value=True) as probe:
            agent.serve(config,'entry')
        self.assertEqual(probe.call_count,2);self.assertEqual(probe.call_args_list[0].kwargs,{'early':True});self.assertEqual(probe.call_args_list[1].kwargs,{})
        self.assertFalse(state.sent or state.early_probed or state.pending or state.leases)

    def test_later_unwritten_query_does_not_block_an_earlier_written_query(self):
        first=self.s.queries({self.f},10)[0]['nonce'];self.s.sent.add(first)
        other=agent.dataclasses.replace(self.f,port=42502,identity=124,translated_port=55001)
        second=self.s.queries({self.f,other},10.1)[0]['nonce']
        self.assertEqual(self.s.probes({self.f,other},10.1),[(first,self.f)])
        self.s.early_probed.add(first);self.assertEqual(self.s.probes({self.f,other},10.2),[])
        self.s.sent.add(second);self.assertEqual(self.s.probes({self.f,other},10.3),[(second,other)])

if __name__=='__main__':unittest.main()
