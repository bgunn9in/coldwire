import importlib.util
from pathlib import Path
import struct
import stat
import sys
import unittest
from unittest import mock

spec=importlib.util.spec_from_file_location('flow_agent',Path(__file__).with_name('agent.py'))
agent=importlib.util.module_from_spec(spec);sys.modules[spec.name]=agent;spec.loader.exec_module(agent)

class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.flow=agent.Flow('192.168.76.30',32497,123,32497)
        self.entry=agent.Entry();self.exit=agent.Exit('192.168.76.10')
    def event(self,stamp,port=32497):
        return agent.EVENT.pack(b'CWP1',stamp,bytes([192,168,76,10]),port,bytes.fromhex('ab'*16),42)
    def proofs(self,messages):return [m for m in messages if 'nonce' in m]
    def test_new_authenticated_event_required(self):
        query=self.entry.queries({self.flow},10)[0];self.exit.query(query,10.1)
        self.assertEqual(self.proofs(self.exit.event(self.event(10000000000),10.2)),[])
        proof=self.proofs(self.exit.event(self.event(10200000000),10.3))[0]
        self.assertTrue(self.entry.confirm(proof,{self.flow},10.4))
        self.assertEqual(self.entry.leases[self.flow][1],20.4)
        self.assertFalse(self.entry.confirm(proof,{self.flow},10.5))
    def test_nat_port_reuse_and_flow_generation(self):
        query=self.entry.queries({self.flow},10)[0];self.exit.query(query,10.1)
        proof=self.proofs(self.exit.event(self.event(10200000000),10.3))[0]
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
        self.assertEqual(set(self.entry.leases),{self.flow,moved})
        self.assertEqual(self.entry.leases[self.flow][1],3.1)
        query3=self.entry.queries({self.flow,moved},4)[0]
        self.assertFalse(self.entry.confirm({'nonce':query3['nonce'],'peer':'ab'*16,'stamp':150},{self.flow,moved},4.1))
    def test_expiry_limits_and_unrelated_events(self):
        query=self.entry.queries({self.flow},1)[0];self.exit.query(query,1)
        self.assertEqual(self.proofs(self.exit.event(self.event(1100000000,40000),1.2)),[])
        self.assertEqual(self.exit.event(b'bad',1.2),[])
        self.assertEqual(self.exit.event(self.event(5000000000),1.2),[])
        self.assertEqual(self.exit.event(self.event(1100000000),5),[])
        self.assertFalse(self.entry.confirm({'nonce':query['nonce'],'peer':'ab'*16,'stamp':2},{self.flow},5))
        for value in ({'nonce':'ab'*16,'port':True},{'nonce':'bad','port':32497},{'nonce':'ab'*16,'port':0},{'nonce':'ab'*16,'port':65536}):self.exit.query(value,10)
        self.assertFalse(self.exit.pending)
        self.entry.leases[self.flow]=('ab'*16,11)
        self.entry.queries({self.flow},12);self.assertFalse(self.entry.leases)
        large={agent.Flow('192.168.76.40',40000+i,i+1,40000+i) for i in range(256)}
        self.assertEqual(len(self.entry.queries(large,20)),4)

    def test_probe_needs_ready_authenticated_hint_and_live_pending_request(self):
        self.entry.escrow_socket=agent.ESCROW_SOCKET
        request=self.entry.queries({self.flow},10)[0];name=request['nonce']
        self.assertFalse(self.entry.acknowledged({'ready':'bad'},10))
        self.assertFalse(self.entry.acknowledged({'ready':'ff'*16},10))
        self.assertTrue(self.entry.acknowledged({'ready':name},10.1))
        self.assertEqual(self.entry.probes({self.flow},10.2),[])
        self.entry.auth_hints[self.flow]=12
        self.assertEqual(self.entry.probes(set(),10.2),[])
        self.assertEqual(self.entry.probes({self.flow},10.2),[(name,self.flow)])
        self.assertFalse(self.entry.leases)
        self.entry.leases[self.flow]=('ab'*16,12)
        self.assertEqual(self.entry.probes({self.flow},10.2),[])
        self.entry.leases[self.flow]=('ab'*16,10.1)
        self.assertEqual(self.entry.probes({self.flow},10.2),[(name,self.flow)])
        self.entry.leases.clear()
        self.entry.probed.add(name);self.assertEqual(self.entry.probes({self.flow},10.3),[])
        self.entry.queries(set(),14)
        self.assertFalse(self.entry.ready);self.assertFalse(self.entry.probed)
        self.assertFalse(self.entry.acknowledged({'ready':name},14))

    def test_reordered_admission_proof_still_needs_post_query_authentication(self):
        request=self.entry.queries({self.flow},10)[0]
        self.assertTrue(self.exit.query(request,10.1))
        before=self.event(10000000000).replace(b'CWP1',b'CWA1')
        self.assertEqual(self.proofs(self.exit.event(before,10.2)),[])
        event=self.event(10200000000).replace(b'CWP1',b'CWA1')
        proof=self.proofs(self.exit.event(event,10.3))[0]
        self.assertIs(proof['recovery'],True)
        self.assertFalse(self.entry.confirm(proof|{'recovery':'yes'},{self.flow},10.4))
        self.assertTrue(self.entry.confirm(proof,{self.flow},10.4))
        self.assertEqual(self.entry.leases[self.flow][1],11.4)

    def test_short_recovery_overlap_preserves_current_lease_and_bounds_peer_flows(self):
        flows={self.flow};peer='ab'*16
        first='00'*16;self.entry.pending[first]=(self.flow,3)
        self.assertTrue(self.entry.confirm({'nonce':first,'peer':peer,'stamp':1},flows,1))
        current_until=self.entry.leases[self.flow][1]
        for i in range(1,5):
            flow=agent.Flow('192.168.76.31',42500+i,123+i,42500+i);flows.add(flow)
            name=f'{i:032x}';self.entry.pending[name]=(flow,3)
            now=1+i*.1
            self.assertTrue(self.entry.confirm({'nonce':name,'peer':peer,'stamp':i+1,'recovery':True},flows,now))
            self.assertEqual(self.entry.leases[flow][1],now+1)
            self.assertLessEqual(len(self.entry.leases),agent.PEER_FLOWS)
            self.assertEqual(self.entry.leases[self.flow][1],current_until)
        self.entry.queries(flows,3);self.assertEqual(set(self.entry.leases),{self.flow})

    def test_unknown_query_pressure_reserves_slots_for_authenticated_hints(self):
        flows={agent.Flow(f'192.168.77.{i//4+1}',40000+i,i+1,40000+i) for i in range(256)}
        for step in range(16):self.entry.queries(flows,20+step*.01)
        self.assertEqual(len(self.entry.pending),agent.MAX_PENDING-16)
        self.entry.auth_hints[self.flow]=30
        requests=self.entry.queries(flows|{self.flow},21)
        self.assertTrue(any(self.entry.pending[v['nonce']][0]==self.flow for v in requests))
    def test_hints_lookup_one_mapping_without_candidate_table(self):
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
        with mock.patch.object(agent,'read_flow',return_value=self.flow) as lookup:
            for value in ({'hint':True},{'hint':0},{'hint':65536},{'hint':'32497'},{'hint':32497,'peer':'ab'*16}):self.assertFalse(self.entry.hint(value,config,10))
            lookup.assert_not_called()
            self.assertTrue(self.entry.hint({'hint':32497},config,10))
            self.assertFalse(self.entry.hint({'hint':32497},config,10.1));self.assertEqual(lookup.call_count,1)
            self.assertEqual(self.entry.current_flows(10.2),{self.flow})
            self.assertFalse(self.entry.leases)
            self.assertEqual(len(self.entry.queries(self.entry.current_flows(10.2),10.2)),1)
        self.assertEqual(self.entry.current_flows(21),set())

    def test_early_local_candidate_still_needs_generation_and_fresh_proof(self):
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
        event=agent.CANDIDATE.pack(b'CWC1',bytes([192,168,76,30]),32497,123)
        value=(self.flow.source,self.flow.port,self.flow.identity,self.flow.translated_port)
        with mock.patch.object(agent.conntrack,'lookup',return_value=value) as lookup,mock.patch.object(agent,'read_flow',return_value=self.flow):
            self.assertTrue(self.entry.candidate(event,config,10))
            lookup.assert_called_once_with(config['entry'],config['exit'],32497,None,original=('192.168.76.30',32497),identity=123)
            self.assertFalse(self.entry.leases)
            query=self.entry.queries(self.entry.current_flows(10),10)[0]
            self.assertIn(query['nonce'],self.entry.pending)
        with mock.patch.object(agent.conntrack,'lookup',side_effect=ValueError('generation changed')):
            self.assertFalse(self.entry.candidate(event,config,11))
        for bad in (b'bad',event.replace(b'CWC1',b'CWC0'),agent.CANDIDATE.pack(b'CWC1',bytes([192,168,76,30]),0,123)):
            self.assertFalse(self.entry.candidate(bad,config,12))

    def test_local_candidate_uses_its_checked_generation_without_a_second_get(self):
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
        flow=agent.Flow('192.168.76.30',42502,123,61000)
        replacement=agent.Flow('192.168.76.40',40000,456,61000)
        event=agent.CANDIDATE.pack(b'CWC1',bytes([192,168,76,30]),flow.port,flow.identity)
        value=(flow.source,flow.port,flow.identity,flow.translated_port)
        with mock.patch.object(agent.conntrack,'lookup',return_value=value) as lookup,mock.patch.object(agent,'read_flow',return_value=replacement) as second:
            self.assertTrue(self.entry.candidate(event,config,10))
            self.assertEqual(self.entry.current_flows(10),{flow})
            self.assertFalse(self.entry.auth_hints)
            second.assert_not_called();lookup.assert_called_once()
        query=self.entry.queries({flow},10)[0]
        self.assertFalse(self.entry.confirm({'nonce':query['nonce'],'peer':'ab'*16,'stamp':100},{replacement},10.1))
        self.assertFalse(self.entry.leases)

    def test_authenticated_hint_wakes_cached_local_candidate_only_on_priority_change(self):
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
        with mock.patch.object(agent,'read_flow',return_value=self.flow) as lookup:
            self.assertTrue(self.entry.hint({'hint':32497},config,10,authenticated=False))
            self.assertNotIn(self.flow,self.entry.auth_hints)
            self.assertTrue(self.entry.hint({'hint':32497},config,10.1))
            self.assertIn(self.flow,self.entry.auth_hints)
            self.assertFalse(self.entry.hint({'hint':32497},config,10.2))
            lookup.assert_called_once()
        self.assertFalse(self.entry.leases)

    def test_hint_pressure_never_evicts_protected_flows_and_caches_stay_bounded(self):
        self.entry.flows[32497]=self.flow;self.entry.observed[32497]=1;self.entry.leases[self.flow]=('ab'*16,100)
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
        with mock.patch.object(agent,'read_flow',side_effect=OSError('temporary netlink failure')):
            for port in range(10000,20000):self.entry.hint({'hint':port},config,2)
        self.assertIn(self.flow,self.entry.current_flows(2))
        self.assertIn(self.flow,self.entry.leases)
        self.assertLessEqual(len(self.entry.flows),agent.MAX_PENDING)
        self.assertLessEqual(len(self.entry.observed),agent.MAX_PENDING)
        self.assertLessEqual(len(self.entry.looked_up),agent.MAX_PENDING)
        self.assertFalse(self.entry.current_flows(20))

    def test_escrow_snapshot_retries_without_extending_lease(self):
        self.entry.escrow_socket=agent.ESCROW_SOCKET;self.entry.leases[self.flow]=('ab'*16,20)
        with mock.patch.object(agent,'notify_escrow',side_effect=[False,True]) as notify:
            agent.sync_escrow(self.entry,10);agent.sync_escrow(self.entry,10.25)
        self.assertEqual(notify.call_count,2);self.assertEqual(self.entry.leases[self.flow][1],20)
        self.assertEqual(self.entry.stats['escrow_notify_failed'],1)

    def test_exit_hint_rate_and_cache_are_bounded(self):
        hints=[]
        for i in range(1000):hints+=self.exit.event(self.event(1000000000,port=10000+i),1)
        self.assertEqual(len([m for m in hints if 'hint' in m]),16)
        for i in range(1000):self.exit.event(self.event(2000000000+i*10000000,port=10000+i),2+i*.01)
        self.assertLessEqual(len(self.exit.hinted),agent.MAX_PENDING)
    def test_nanosecond_cutoff_and_buffered_TLS_records(self):
        request={'nonce':'cd'*16,'port':32497}
        self.exit.query(request,10,cutoff_ns=10000000123)
        self.assertEqual(self.proofs(self.exit.event(self.event(10000000122),10.1)),[])
        self.assertEqual(len(self.proofs(self.exit.event(self.event(10000000124),10.1))),1)
        class BufferedTLS:
            def __init__(self):self.blocks=[b'{"n":1}\n',b'{"n":2}\n']
            def setsockopt(self,level,option,value):
                assert (level,option,value)==(agent.socket.IPPROTO_TCP,agent.socket.TCP_NODELAY,1)
            def setblocking(self,value):pass
            def recv(self,size):
                if self.blocks:return self.blocks.pop(0)
                raise agent.ssl.SSLWantReadError()
        self.assertEqual(agent.Stream(BufferedTLS()).read(),[{'n':1},{'n':2}])

    def test_confirm_is_immediate_disconnect_keeps_bounded_lease(self):
        clock=[10.0];steps=[0];handlers={};queries=[];installs=[]
        connection=mock.Mock()
        class FakeStream:
            def __init__(self,sock):self.socket=sock;self.outgoing=bytearray()
            def queue(self,message):queries.append(message)
            def read(self):
                if steps[0]==1:return [{'hint':32497}]
                if steps[0]==3:raise EOFError
                return [{'nonce':queries[0]['nonce'],'peer':'ab'*16,'stamp':100}]
        def select(readers,writers,errors,timeout):
            steps[0]+=1;clock[0]=10+(steps[0]-1)*.02
            if steps[0] in (1,2,3):return [connection],[],[]
            if steps[0]==4:handlers[agent.signal.SIGTERM]()
            return [],[],[]
        def install(state,flows,now):installs.append((now,set(state.leases)))
        context=mock.Mock();context.wrap_socket.return_value=connection
        config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497,'status':'unused'}
        with mock.patch.object(agent.os,'geteuid',return_value=0,create=True), \
             mock.patch.object(agent.Path,'read_text',return_value='kit-entry'), \
             mock.patch.object(agent,'context',return_value=context), \
             mock.patch.object(agent.signal,'signal',side_effect=lambda sig,fn:handlers.__setitem__(sig,fn)), \
             mock.patch.object(agent.socket,'create_connection',return_value=connection), \
             mock.patch.object(agent,'Stream',FakeStream), \
             mock.patch.object(agent.select,'select',side_effect=select), \
             mock.patch.object(agent.time,'monotonic',side_effect=lambda:clock[0]), \
             mock.patch.object(agent,'read_flow',return_value=self.flow), \
             mock.patch.object(agent,'install_leases',side_effect=install), \
             mock.patch.object(agent,'snapshot'):
            agent.serve(config,'entry')
        self.assertEqual(installs[0],(10.0,set()))
        self.assertEqual(installs[1],(10.02,{self.flow}))
        self.assertEqual(installs[2],(10.06,set()))
        self.assertLess(installs[2][0],10+agent.POLL_SECONDS)

    def test_escrow_is_optional_and_follows_successful_kernel_install(self):
        self.entry.leases[self.flow]=('ab'*16,20)
        with mock.patch.object(agent.subprocess,'run') as nft, mock.patch.object(agent,'notify_escrow') as notify:
            agent.install_leases(self.entry,{self.flow},10)
            notify.assert_not_called()
            self.entry.escrow_socket=agent.ESCROW_SOCKET
            notify.side_effect=lambda state: bool(nft.call_count==2)
            agent.install_leases(self.entry,{self.flow},10)
            self.assertNotIn('escrow_notify_failed',self.entry.stats)
            nft.side_effect=agent.subprocess.CalledProcessError(1,'nft')
            with self.assertRaises(agent.subprocess.CalledProcessError):agent.install_leases(self.entry,{self.flow},10)
            self.assertEqual(notify.call_count,1)

    def test_escrow_encoding_revocation_and_unavailable_socket(self):
        self.entry.escrow_socket=agent.ESCROW_SOCKET
        self.entry.leases[self.flow]=('ab'*16,20)
        directory=mock.Mock(st_mode=stat.S_IFDIR|0o700,st_uid=0)
        endpoint=mock.Mock(st_mode=stat.S_IFSOCK|0o600,st_uid=0)
        connection=mock.MagicMock();connection.__enter__.return_value=connection
        sent=[]
        connection.sendto.side_effect=lambda data,path: sent.append(data) or len(data)
        with mock.patch.object(agent.Path,'lstat',side_effect=lambda path:directory if path==agent.Path(agent.ESCROW_SOCKET).parent else endpoint,autospec=True), mock.patch.object(agent.socket,'socket',return_value=connection),mock.patch.object(agent.socket,'AF_UNIX',1,create=True):
            self.assertTrue(agent.notify_escrow(self.entry))
            self.assertEqual(sent[-1],struct.pack('!4sH',b'CWE1',1)+agent.ESCROW_RECORD.pack(bytes([192,168,76,30]),32497,123,20000000000))
            self.assertTrue(agent.probe_escrow(self.entry,self.flow,10))
            self.assertEqual(sent[-1],b'CWS1'+agent.ESCROW_RECORD.pack(bytes([192,168,76,30]),32497,123,11000000000))
            self.entry.leases.clear();self.assertTrue(agent.notify_escrow(self.entry));self.assertEqual(sent[-1],b'CWE1\0\0')
            endpoint.st_mode=stat.S_IFSOCK|0o666
            self.assertFalse(agent.notify_escrow(self.entry))
            self.assertFalse(agent.probe_escrow(self.entry,self.flow,10))
            endpoint.st_mode=stat.S_IFLNK|0o600
            self.assertFalse(agent.notify_escrow(self.entry))
            self.entry.escrow_socket='/tmp/other.sock';self.assertFalse(agent.notify_escrow(self.entry))
        with mock.patch.object(agent,'notify_escrow',return_value=False),mock.patch.object(agent.subprocess,'run'):
            agent.install_leases(self.entry,set(),10)
            self.assertEqual(self.entry.stats['escrow_notify_failed'],1)

if __name__=='__main__':unittest.main()
