"""Bounded synthetic UDP matrix and header-only IPv4 capture; no host settings changed."""
import argparse
import errno
import json
from pathlib import Path
import select
import socket
import struct
import threading
import time

SIZES = (64, 256, 512, 1000, 1200, 1280, 1350, 1400, 1440, 1460, 2048)
MAGIC = b'PMTU07A'
HEADER = struct.Struct('!7scHH')

def packet(kind, size, seq, length=None):
    length = size if length is None else length
    return HEADER.pack(MAGIC, kind.encode(), size, seq) + bytes([(size + seq) % 251]) * (length-HEADER.size)

def decode(data):
    magic, kind, size, seq = HEADER.unpack_from(data)
    if magic != MAGIC or size not in SIZES: raise ValueError('not synthetic probe')
    return kind.decode(), size, seq

def outer_ipv4_sizes(payload_bytes, tun_mtu, s4=12):
    """IPv4+UDP+AWG data framing, including bounded 16-byte inner padding."""
    if not 0 <= payload_bytes <= 65507 or not 576 <= tun_mtu <= 65535 or not 0 <= s4 <= 65535:
        raise ValueError('invalid payload, TUN MTU or S4')
    remaining=payload_bytes+8;chunk=((tun_mtu-20)//8)*8;result=[]
    while remaining:
        body=min(remaining,chunk);inner=20+body;remaining-=body
        padded=min((inner+15)//16*16,tun_mtu)
        result.append(20+8+16+16+s4+padded)
    return result

def client_mtu_for_ipv4_path(path_mtu, s4=12):
    if not isinstance(path_mtu,int) or not isinstance(s4,int) or path_mtu<576 or s4<0:
        raise ValueError('invalid measured IPv4 PMTU or S4')
    mtu=path_mtu-(20+8+16+16+s4)
    if mtu<576:raise ValueError('path cannot carry the minimum inner IPv4 MTU')
    return mtu

def counters():
    lines=Path('/proc/net/snmp').read_text().splitlines(); result={}
    for a,b in zip(lines[::2],lines[1::2]):
        names=a.split();values=b.split()
        for key,value in zip(names[1:],values[1:]):
            if names[0] in ('Ip:','Udp:','Icmp:'): result[names[0][:-1]+'.'+key]=int(value)
    return result

class Capture:
    def __init__(self, interfaces, outer_peer, port, limit=4000):
        self.peer=outer_peer;self.port=port;self.limit=limit;self.records=[];self.running=True
        self.sockets=[]
        for iface in interfaces:
            s=socket.socket(socket.AF_PACKET,socket.SOCK_DGRAM,socket.htons(0x0003));s.bind((iface,0));s.setblocking(False);self.sockets.append((s,iface))
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def loop(self):
        while self.running and len(self.records)<self.limit:
            ready,_,_=select.select([s for s,_ in self.sockets],[],[],.1)
            for s in ready:
                try: data,address=s.recvfrom(65535)
                except BlockingIOError: continue
                if len(data)<20 or data[0]>>4!=4:continue
                ihl=(data[0]&15)*4;total=struct.unpack_from('!H',data,2)[0];frag=struct.unpack_from('!H',data,6)[0];proto=data[9]
                src=socket.inet_ntoa(data[12:16]);dst=socket.inet_ntoa(data[16:20]);offset=(frag&8191)*8
                iface=next(i for sk,i in self.sockets if sk is s)
                record={'time':time.time(),'interface':iface,'direction':'outgoing' if address[2]==socket.PACKET_OUTGOING else 'incoming','src':src,'dst':dst,'ip_bytes':total,'captured_bytes':len(data),'ip_id':struct.unpack_from('!H',data,4)[0],'fragment_offset':offset,'more_fragments':bool(frag&8192),'df':bool(frag&16384),'protocol':proto}
                if proto==17:
                    if offset==0 and len(data)>=ihl+8:
                        sport,dport,length,_=struct.unpack_from('!HHHH',data,ihl);record.update(source_port=sport,destination_port=dport,udp_bytes=length)
                        if self.port not in (sport,dport) and 29177 not in (sport,dport):continue
                        if self.port in (sport,dport):
                            try:
                                kind,size,seq=decode(data[ihl+8:]);record.update(probe_kind=kind,payload_size=size,sequence=seq)
                            except (ValueError,struct.error):continue
                    elif self.peer and self.peer not in (src,dst) and not src.startswith('10.88.31.') and not dst.startswith('10.88.31.'):continue
                elif proto==1 and len(data)>=ihl+8:
                    record.update(icmp_type=data[ihl],icmp_code=data[ihl+1])
                    if (data[ihl],data[ihl+1])!=(3,4):continue
                    record['next_hop_mtu']=struct.unpack_from('!H',data,ihl+6)[0]
                else:continue
                self.records.append(record)
    def close(self):
        self.running=False;self.thread.join(timeout=2)
        for s,_ in self.sockets:s.close()
        return self.records

def server(args):
    before=counters();capture=Capture(args.interfaces,args.peer,args.port);events=[]
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind((args.bind,args.port));sock.settimeout(.2);until=time.monotonic()+args.duration
        print('PMTU_SERVER_READY',flush=True)
        while time.monotonic()<until:
            try:data,peer=sock.recvfrom(8192)
            except socket.timeout:continue
            if peer[0]!=args.client:continue
            try:kind,size,seq=decode(data)
            except (ValueError,struct.error):continue
            if kind=='F':break
            expected=packet(kind,size,seq,64 if kind=='Q' else None)
            if data!=expected:continue
            event={'time':time.time(),'kind':kind,'size':size,'sequence':seq,'received_bytes':len(data)}
            try:
                response=packet('S',size,seq) if kind=='Q' else packet('A',size,seq,64)
                event['sent_bytes']=sock.sendto(response,peer)
            except OSError as e:event['errno']=e.errno;event['emsgsize']=e.errno==errno.EMSGSIZE
            events.append(event)
    after=counters();records=capture.close()
    print(json.dumps({'role':'server','events':events,'capture':records,'counter_delta':{k:after[k]-v for k,v in before.items()},'capture_limit':capture.limit}),flush=True)

def client(args):
    before=counters();capture=Capture(args.interfaces,args.peer,args.port);results=[]
    def exchange(sock,kind,size,seq):
        start=time.monotonic();entry={'time':time.time(),'direction':'server_to_client' if kind=='Q' else 'client_to_server','payload_bytes':size,'internal_ip_bytes_unfragmented':size+28,'sequence':seq,'sent':1,'received':0,'rtt_ms':None,'emsgsize':False}
        try:
            sock.sendto(packet(kind,size,seq,64 if kind=='Q' else None),(args.bind,args.port))
            until=time.monotonic()+args.timeout
            while time.monotonic()<until:
                sock.settimeout(max(.001,until-time.monotonic()))
                data,_=sock.recvfrom(8192)
                expected=packet('S' if kind=='Q' else 'A',size,seq,None if kind=='Q' else 64)
                if data==expected:entry.update(received=1,rtt_ms=round((time.monotonic()-start)*1000,3));break
        except socket.timeout:pass
        except OSError as e:entry.update(errno=e.errno,emsgsize=e.errno==errno.EMSGSIZE)
        return entry
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind((args.client,19998))
        for size in SIZES:
            for seq in range(args.trials):
                for kind in ('C','Q'):
                    result=exchange(sock,kind,size,seq);results.append(result);time.sleep(.04)
            print(json.dumps({'size':size,'results':[{d:sum(r['received'] for r in results if r['payload_bytes']==size and r['direction']==d)} for d in ['client_to_server','server_to_client']]}),flush=True)
        sock.sendto(packet('F',64,0,64),(args.bind,args.port))
    after=counters();records=capture.close();return {'role':'client','results':results,'capture':records,'counter_delta':{k:after[k]-v for k,v in before.items()},'trials':args.trials,'sizes':SIZES,'capture_limit':capture.limit}

def main():
    p=argparse.ArgumentParser();p.add_argument('role',choices=['server','client']);p.add_argument('--bind',default='10.88.31.1');p.add_argument('--client',default='10.88.31.2');p.add_argument('--port',type=int,default=19999);p.add_argument('--peer',default='');p.add_argument('--interfaces',nargs='+',required=True);p.add_argument('--duration',type=int,default=180);p.add_argument('--trials',type=int,default=5);p.add_argument('--timeout',type=float,default=1.2);p.add_argument('--output')
    a=p.parse_args()
    if a.role=='server':server(a)
    else:
        result=client(a)
        if a.output:Path(a.output).write_text(json.dumps(result,indent=2))
        else:print(json.dumps(result))
if __name__=='__main__':main()
