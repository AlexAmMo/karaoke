{ Private, authenticated host-to-engine PCM transport. The web service owns pairing. }
unit UKaraokeMobileAudio;
{$mode objfpc}{$H+}
interface
const KaraokeMaxSingers = 10;
      MobileFrameSamples = 960;
type TMobileFrame = array[0..MobileFrameSamples-1] of SmallInt;
function MobileOpen(const TurnSecret: RawByteString): boolean;
procedure MobileClose;
function MobileReceived(Slot: integer): integer;
function MobileMissing(Slot: integer): integer;
function MobileRejected: integer;
function MobilePort: integer;
function MobileRead(out Slot: integer; out Frame: TMobileFrame): boolean;
implementation
uses SysUtils, {$IFDEF MSWINDOWS} WinSock2 {$ELSE} BaseUnix {$ENDIF}, Sockets;
type TPacket = packed record
  Secret: array[0..31] of AnsiChar;
  Slot: byte;
  Seq: Cardinal;
  Frame: TMobileFrame;
  Extra: byte; { Detect and drop oversized datagrams. }
end;
var SocketFD: TSocket;
    Port: integer;
    Secret: RawByteString;
    Accepted,Missing: array[0..KaraokeMaxSingers-1] of integer;
    Rejections: integer;
    LastSeq: array[0..KaraokeMaxSingers-1] of Int64;
function MobileReceived(Slot: integer): integer;
begin Result:=Accepted[Slot]; end;
function MobileMissing(Slot: integer): integer;
begin Result:=Missing[Slot]; end;
function MobileRejected: integer;
begin Result:=Rejections; end;
function MobilePort: integer;
begin Result:=Port; end;
procedure MobileClose;
begin
  if Port <> 0 then CloseSocket(SocketFD);
  Port:=0; Secret:='';
end;
function MobileOpen(const TurnSecret: RawByteString): boolean;
var Addr: TInetSockAddr; Size: TSockLen; I: integer;
    {$IFDEF MSWINDOWS} Mode: u_long; {$ENDIF}
begin
  MobileClose; Result:=false;
  if Length(TurnSecret)<>32 then Exit;
  for I:=1 to Length(TurnSecret) do
    if not (TurnSecret[I] in ['0'..'9','a'..'f']) then Exit;
  SocketFD:=fpSocket(AF_INET,SOCK_DGRAM,0);
  if SocketFD=TSocket(-1) then Exit;
  try
    FillChar(Addr,SizeOf(Addr),0);
    Addr.sin_family:=AF_INET; Addr.sin_addr:=StrToNetAddr('127.0.0.1');
    if fpBind(SocketFD,@Addr,SizeOf(Addr))<>0 then Exit;
    {$IFDEF MSWINDOWS}
    Mode:=1;
    if WinSock2.ioctlsocket(SocketFD,LongInt(FIONBIO),Mode)<>0 then Exit;
    {$ELSE}
    if fpFcntl(SocketFD,F_SETFL,O_NONBLOCK)<>0 then Exit;
    {$ENDIF}
    Size:=SizeOf(Addr);
    if fpGetSockName(SocketFD,@Addr,@Size)<>0 then Exit;
    Port:=ntohs(Addr.sin_port); Secret:=TurnSecret;
    FillChar(Accepted,SizeOf(Accepted),0); FillChar(Missing,SizeOf(Missing),0); Rejections:=0;
    for I:=0 to High(LastSeq) do LastSeq[I]:=-1;
    Result:=true;
  finally
    if not Result then CloseSocket(SocketFD);
  end;
end;
function MobileRead(out Slot: integer; out Frame: TMobileFrame): boolean;
var Packet: TPacket; Received,I: integer; Seq: Cardinal;
begin
  Slot:=-1; Result:=false;
  if Port=0 then Exit;
  Received:=fpRecv(SocketFD,@Packet,SizeOf(Packet),0);
  if Received<0 then Exit;
  Result:=true; { A datagram was consumed, even if it must be discarded. }
  Inc(Rejections);
  if (Received<>SizeOf(Packet)-1) or (Packet.Slot>=KaraokeMaxSingers) then Exit;
  if not CompareMem(@Packet.Secret[0],@Secret[1],32) then Exit;
  Seq:=LEtoN(Packet.Seq);
  if Int64(Seq)<=LastSeq[Packet.Slot] then Exit;
  Dec(Rejections); Inc(Accepted[Packet.Slot]);
  if LastSeq[Packet.Slot]>=0 then Inc(Missing[Packet.Slot],Int64(Seq)-LastSeq[Packet.Slot]-1);
  LastSeq[Packet.Slot]:=Seq; Slot:=Packet.Slot;
  for I:=0 to High(Frame) do Frame[I]:=LEtoN(Packet.Frame[I]);
end;
finalization
  MobileClose;
end.
