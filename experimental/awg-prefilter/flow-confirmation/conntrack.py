# SPDX-License-Identifier: MIT
"""One IPv4/UDP conntrack GET by original or reply tuple; never dump the table."""
import errno
import ipaddress
import secrets
import socket
import struct

HEADER=struct.Struct('=IHHII')
ATTRIBUTE=struct.Struct('=HH')

def attribute(kind,value):
    length=ATTRIBUTE.size+len(value)
    return ATTRIBUTE.pack(length,kind)+value+b'\0'*((-length)%4)

def attributes(data):
    result={};offset=0
    while offset<len(data):
        if len(data)-offset<4:raise ValueError('Short netlink attribute')
        size,kind=ATTRIBUTE.unpack_from(data,offset);kind&=0x3fff
        if size<4 or offset+size>len(data) or kind in result:raise ValueError('Invalid netlink attribute')
        result[kind]=data[offset+4:offset+size];offset+=(size+3)&~3
    if offset!=len(data):raise ValueError('Invalid attribute padding')
    return result

def tuple_bytes(source,destination,sport,dport):
    ip=attribute(1,ipaddress.IPv4Address(source).packed)+attribute(2,ipaddress.IPv4Address(destination).packed)
    udp=attribute(1,b'\x11')+attribute(2,struct.pack('!H',sport))+attribute(3,struct.pack('!H',dport))
    return attribute(0x8001,ip)+attribute(0x8002,udp)

def parse_tuple(data):
    value=attributes(data);ip=attributes(value[1]);udp=attributes(value[2])
    if len(ip[1])!=4 or len(ip[2])!=4 or udp[1]!=b'\x11' or len(udp[2])!=2 or len(udp[3])!=2:
        raise ValueError('Invalid IPv4/UDP tuple')
    return (str(ipaddress.IPv4Address(ip[1])),str(ipaddress.IPv4Address(ip[2])),struct.unpack('!H',udp[2])[0],struct.unpack('!H',udp[3])[0])

def parse(data,sequence,entry,exit,port,translated_port,expected_original=None,expected_id=None):
    try:
        if len(data)<HEADER.size:raise ValueError('Short netlink header')
        size,kind,flags,seq,_=HEADER.unpack_from(data)
        # Conntrack GET marks its single object MULTI too; no dump was requested.
        if size!=len(data) or seq!=sequence or flags&~2:raise ValueError('Unexpected netlink reply')
        if kind==2:
            if len(data)<20:raise ValueError('Short netlink error')
            error=struct.unpack_from('=i',data,16)[0]
            if error==-errno.ENOENT:return None
            if error>=0:raise ValueError('Unexpected netlink acknowledgement')
            raise OSError(-error,'Conntrack GET failed')
        if kind!=0x100 or len(data)<20 or data[16:20]!=b'\x02\x00\x00\x00':raise ValueError('Unexpected conntrack message')
        values=attributes(data[20:]);original=parse_tuple(values[1]);reply=parse_tuple(values[2])
        if len(values[12])!=4 or len(values[3])!=4:raise ValueError('Invalid conntrack identity/status')
        identity=struct.unpack('!I',values[12])[0];status=struct.unpack('!I',values[3])[0]
        if original[1]!=entry or original[3]!=port or reply[:3]!=(exit,entry,port) or not reply[3] or not original[2] or not identity or not status&8:
            raise ValueError('Conntrack mapping mismatch')
        if translated_port is not None and reply[3]!=translated_port:raise ValueError('Reply port mismatch')
        if expected_original is not None and (original[0],original[2])!=expected_original:raise ValueError('Original tuple mismatch')
        if expected_id is not None and identity!=expected_id:raise ValueError('Conntrack generation mismatch')
        return (original[0],original[2],identity,reply[3])
    except KeyError as error:raise ValueError('Incomplete conntrack reply') from error

def lookup(entry,exit,port,translated_port,original=None,identity=None):
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError('Invalid UDP port')
    if original is None:
        if type(translated_port) is not int or not 1<=translated_port<=65535:raise ValueError('Invalid translated port')
        value=attribute(0x8002,tuple_bytes(exit,entry,port,translated_port))
    else:
        source,sport=original
        if type(sport) is not int or not 1<=sport<=65535 or type(identity) is not int or not 0<identity<2**32:raise ValueError('Invalid original identity')
        value=attribute(0x8001,tuple_bytes(source,entry,sport,port))
    sequence=secrets.randbits(32)
    body=b'\x02\0\0\0'+value
    request=HEADER.pack(HEADER.size+len(body),0x101,1,sequence,0)+body
    with socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,12) as connection:
        connection.bind((0,0));connection.settimeout(.25)
        if connection.sendto(request,(0,0))!=len(request):raise OSError('Short conntrack request')
        data,_,flags,peer=connection.recvmsg(8192)
        if flags&(socket.MSG_TRUNC|socket.MSG_CTRUNC) or peer!=(0,0):raise ValueError('Invalid conntrack sender/size')
        return parse(data,sequence,entry,exit,port,translated_port,original,identity)
