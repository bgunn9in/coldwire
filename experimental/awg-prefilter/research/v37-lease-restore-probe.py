#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Disposable kit-entry only: real nft timeout/conntrack restore checks, no hooks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--vm-test',action='store_true',required=True)
p.add_argument('--agent-directory',type=Path,required=True)
a=p.parse_args()
assert os.geteuid()==0 and Path('/etc/hostname').read_text().strip()=='kit-entry'
sys.path.insert(0,str(a.agent_directory));import agent
config={'entry':'192.168.76.10','exit':'192.168.76.20','vpn_port':32497}
flow=next((f for port in (32497,32498,42501,42502,42503) if (f:=agent.read_flow(config,port)) and f.source in ('192.168.76.30','192.168.76.31')),None)
assert flow,'Probe an original native lab client before running this check'
agent.TABLE='cw37_lease_ip';agent.LATE_TABLE='cw37_lease_bridge'
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def nft(*args,data=None):return subprocess.run(['nft',*args],input=data,text=True,capture_output=True,timeout=2,check=True)
owned=[]
try:
 for family,table in [('ip',agent.TABLE),('bridge',agent.LATE_TABLE)]:
  assert subprocess.run(['nft','list','table',family,table],capture_output=True).returncode!=0
  nft('-f','-',data=f'table {family} {table} {{ set trusted {{ typeof ip saddr . udp sport . ct id; flags timeout; timeout 10s; }}\n}}\n')
  owned.append((family,table))
  nft('-f','-',data=f'add element {family} {table} trusted {{ {flow.source} . {flow.port} . {flow.identity} timeout 3s }}\n')
 with tempfile.TemporaryDirectory(prefix='cw37-lease-',dir='/root') as directory:
  path=Path(directory)/'status.json';config['status']=str(path)
  previous=agent.Entry(agent.ESCROW_SOCKET,True);previous.leases[flow]=('ab'*16,time.monotonic()+5)
  value={'time_ns':time.monotonic_ns(),**agent.entry_values(previous,config,boot,time.monotonic())}
  path.write_text(json.dumps(value));path.chmod(0o600)
  state=agent.Entry(agent.ESCROW_SOCKET,True)
  assert agent.restore_leases(state,config,boot)==1
  assert state.leases[flow][1]<=previous.leases[flow][1]
  assert 0<state.leases[flow][1]-time.monotonic()<=3
  restored_deadline=state.leases[flow][1]
  assert not state.pending and not state.peer_stamp and not state.auth_hints
  path.chmod(0o644);assert agent.restore_leases(agent.Entry(agent.ESCROW_SOCKET,True),config,boot)==0;path.chmod(0o600)
  assert agent.restore_leases(agent.Entry(agent.ESCROW_SOCKET,True),config,'other-boot')==0
  wrong=json.loads(path.read_text());wrong['leases'][0]['identity']=flow.identity%0xffffffff+1
  for family,table in owned:
   nft('-f','-',data=f"add element {family} {table} trusted {{ {flow.source} . {flow.port} . {wrong['leases'][0]['identity']} timeout 3s }}\n")
  path.write_text(json.dumps(wrong));assert agent.restore_leases(agent.Entry(agent.ESCROW_SOCKET,True),config,boot)==0
  path.write_text(json.dumps(value))
  nft('flush','set','bridge',agent.LATE_TABLE,'trusted')
  assert agent.restore_leases(agent.Entry(agent.ESCROW_SOCKET,True),config,boot)==0
  value['lease_context'][-1]=False;path.write_text(json.dumps(value))
  assert agent.restore_leases(agent.Entry(),config,boot)==1
  time.sleep(3.1)
  assert agent.restore_leases(agent.Entry(),config|{'status':str(path)},boot)==0
  kernel=json.loads(nft('-j','list','set','ip',agent.TABLE,'trusted').stdout)
  assert not next(v['set'] for v in kernel['nftables'] if 'set' in v).get('elem')
  print(json.dumps({'real_kernel_expiry':True,'same_conntrack_generation_required':True,'both_sets_required':True,'private_cache_required':True,'boot_scope_required':True,'original_deadline':previous.leases[flow][1],'restored_deadline':restored_deadline,'no_hooks_installed':True}))
finally:
 for family,table in reversed(owned):nft('delete','table',family,table)
