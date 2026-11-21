{ Private, authenticated host-to-engine PCM transport. The web service owns pairing. }
unit UKaraokeMobileAudio;
{$mode objfpc}{$H+}
interface
const KaraokeMaxSingers = 10;
      MobileFrameSamples = 960;
type TMobileFrame = array[0..MobileFrameSamples-1] of SmallInt;
     TMobileSink = procedure(Slot: integer; var Frame: TMobileFrame; EndTick: Int64; Discontinuity: boolean);
function MobileOpen(const TurnSecret: RawByteString): boolean;
procedure MobileClose;
procedure MobileArm(Slots: Word; Sink: TMobileSink);
procedure MobileSetPaused(Value: boolean);
function MobileDiscarded: integer;
function MobileReceived(Slot: integer): integer;
function MobileMissing(Slot: integer): integer;
function MobileRejected: integer;
function MobilePort: integer;
implementation
uses Classes, SysUtils, SDL2, UKaraokeCaptureHistory, {$IFDEF MSWINDOWS} WinSock2 {$ELSE} BaseUnix {$ENDIF}, Sockets;
type TPacket = packed record
  Secret: array[0..31] of AnsiChar;
  Slot: byte;
  Seq: Cardinal;
  Frame: TMobileFrame;
  Extra: byte; { Detect and drop oversized datagrams. }
end;
type TReceiver = class(TThread)
  protected procedure Execute; override;
  end;
var Receiver: TReceiver;
    Feed: TMobileSink;
    ActiveSlots: Word;
    Paused, Discarded: LongInt;
    SocketFD: TSocket;
    Port: integer;
    Secret: RawByteString;
    Accepted,Missing: array[0..KaraokeMaxSingers-1] of integer;
    Rejections: integer;
    LastSeq: array[0..KaraokeMaxSingers-1] of Int64;
function MobileDiscarded: integer;
begin Result:=InterlockedCompareExchange(Discarded,0,0); end;
procedure MobileSetPaused(Value: boolean);
begin InterlockedExchange(Paused,Ord(Value)); end;
procedure MobileArm(Slots: Word; Sink: TMobileSink);
begin
  if (Port=0) or Assigned(Receiver) then Exit;
  ActiveSlots:=Slots; Feed:=Sink; MobileSetPaused(false);
  Receiver:=TReceiver.Create(true); Receiver.FreeOnTerminate:=false; Receiver.Start;
end;
function MobileReceived(Slot: integer): integer;
begin Result:=InterlockedCompareExchange(Accepted[Slot],0,0); end;
function MobileMissing(Slot: integer): integer;
begin Result:=InterlockedCompareExchange(Missing[Slot],0,0); end;
function MobileRejected: integer;
begin Result:=InterlockedCompareExchange(Rejections,0,0); end;
function MobilePort: integer;
begin Result:=Port; end;
procedure MobileClose;
begin
  if Assigned(Receiver) then
  begin
    Receiver.Terminate; Receiver.WaitFor; FreeAndNil(Receiver);
  end;
  Feed:=nil; ActiveSlots:=0;
  if Port <> 0 then CloseSocket(SocketFD);
  Port:=0; Secret:='';
end;
function MobileOpen(const TurnSecret: RawByteString): boolean;
var Addr: TInetSockAddr; Size: TSockLen; I,BufferBytes: integer;
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
    BufferBytes:=512*1024;
    fpSetSockOpt(SocketFD,SOL_SOCKET,SO_RCVBUF,@BufferBytes,SizeOf(BufferBytes));
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
    FillChar(Accepted,SizeOf(Accepted),0); FillChar(Missing,SizeOf(Missing),0); Rejections:=0; Discarded:=0;
    for I:=0 to High(LastSeq) do LastSeq[I]:=-1;
    Result:=true;
  finally
    if not Result then CloseSocket(SocketFD);
  end;
end;
function MobileRead(out Slot: integer; out Frame: TMobileFrame; out Gap: boolean): boolean;
var Packet: TPacket; Received,I: integer; Seq: Cardinal;
begin
  Slot:=-1; Gap:=false; Result:=false;
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
  if LastSeq[Packet.Slot]>=0 then
  begin
    Gap:=Int64(Seq)>LastSeq[Packet.Slot]+1;
    Inc(Missing[Packet.Slot],Int64(Seq)-LastSeq[Packet.Slot]-1);
  end;
  LastSeq[Packet.Slot]:=Seq; Slot:=Packet.Slot;
  for I:=0 to High(Frame) do Frame[I]:=LEtoN(Packet.Frame[I]);
end;
procedure TReceiver.Execute;
var Frame: TMobileFrame; Slot: integer; Previous,NowMs: QWord; Stale,Gap: boolean;
    NeedsReset: array[0..KaraokeMaxSingers-1] of boolean;
    Clocks: array[0..KaraokeMaxSingers-1] of TDeviceCaptureClock;
    TickRate, EndTick: Int64; I: integer;
begin
  for I:=0 to High(Clocks) do Clocks[I].Reset;
  TickRate:=SDL_GetPerformanceFrequency;
  FillChar(NeedsReset,SizeOf(NeedsReset),1);
  Previous:=GetTickCount64; Stale:=false;
  while not Terminated do
  begin
    NowMs:=GetTickCount64;
    if NowMs-Previous>200 then Stale:=true;
    Previous:=NowMs;
    if not MobileRead(Slot,Frame,Gap) then
    begin
      Stale:=false; Sleep(2); Continue;
    end;
    if Slot<0 then Continue;
    if Stale or (InterlockedCompareExchange(Paused,0,0)<>0) or ((ActiveSlots and (1 shl Slot))=0) then
    begin Inc(Discarded); NeedsReset[Slot]:=true; Continue; end;
    Gap:=Gap or NeedsReset[Slot];
    // The bridge supplies a sequence for each 20 ms PCM packet. Map that
    // media cadence once per singer instead of scoring network arrival jitter.
    EndTick:=Clocks[Slot].Align(SDL_GetPerformanceCounter,TickRate,
      (LastSeq[Slot]+1)*(MobileFrameSamples/48000.0),Gap);
    Feed(Slot,Frame,EndTick,Gap);
    NeedsReset[Slot]:=false;
  end;
end;
finalization
  MobileClose;
end.
