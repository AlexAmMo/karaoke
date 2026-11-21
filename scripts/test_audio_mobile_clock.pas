{ Synthetic UDP packets only: no microphone, playback device or audible output. }
program test_audio_mobile_clock;
{$mode objfpc}{$H+}
uses {$IFDEF UNIX}cthreads,{$ENDIF} Classes, SysUtils, SDL2, Sockets,
  UKaraokeCaptureHistory, UKaraokeMobileAudio;

type TPacket = packed record
  Secret: array[0..31] of AnsiChar;
  Slot: Byte;
  Seq: Cardinal;
  Frame: TMobileFrame;
end;

var Sender: TSocket; Address: TInetSockAddr; Packet: TPacket;
    Seen: LongInt; Gaps: array[0..4] of Boolean; Ends, Arrivals: array[0..4] of Int64;
    Started, Sent, Frequency: Int64;

procedure Check(Value: Boolean; const MessageText: String);
begin
  if not Value then raise Exception.Create(MessageText);
end;

procedure CheckShortPauseClock;
var Clock: TDeviceCaptureClock; Gap: Boolean; Expected, BeforeFix, AfterFix: Int64;
begin
  { Fixed microsecond ticks: a 45 ms pause was previously smoothed as drift. }
  Expected := 1085000;
  Clock.Reset; Gap := false;
  Clock.Align(1000000, 1000000, 0.02, Gap);
  Clock.Align(1020000, 1000000, 0.04, Gap);
  BeforeFix := Clock.Align(Expected, 1000000, 0.06, Gap);
  Check(not Gap and (Expected - BeforeFix > 44000), 'Control did not retain the short-pause error');
  Gap := true;
  AfterFix := Clock.Align(Expected, 1000000, 0.06, Gap);
  Check(AfterFix = Expected, 'Pause discontinuity did not reset the logical clock');
  Writeln('PASS fixed 45 ms pause: control error=', BeforeFix - Expected,
    ' us; corrected error=', AfterFix - Expected, ' us');
end;

procedure Receive(Slot: Integer; var Frame: TMobileFrame; EndTick: Int64; Discontinuity: Boolean);
var Index: Integer;
begin
  Index := InterlockedCompareExchange(Seen, 0, 0);
  if Index <= High(Gaps) then
  begin
    Gaps[Index] := Discontinuity; Ends[Index] := EndTick;
    Arrivals[Index] := SDL_GetPerformanceCounter;
  end;
  InterlockedIncrement(Seen);
end;

procedure Send(Sequence: Cardinal);
var Deadline: QWord;
begin
  Packet.Seq := NtoLE(Sequence);
  Check(fpSendTo(Sender, @Packet, SizeOf(Packet), 0, @Address, SizeOf(Address)) = SizeOf(Packet),
    'Synthetic packet was not sent');
  Deadline := GetTickCount64 + 2000;
  while (InterlockedCompareExchange(Seen, 0, 0) <= Sequence) and (GetTickCount64 < Deadline) do Sleep(1);
  Check(InterlockedCompareExchange(Seen, 0, 0) > Sequence, 'Synthetic packet was not delivered');
end;

begin
  CheckShortPauseClock;
  Check(MobileOpen(StringOfChar('a', 32)), 'Cannot open test transport');
  Sender := fpSocket(AF_INET, SOCK_DGRAM, 0);
  try
    FillChar(Address, SizeOf(Address), 0);
    Address.sin_family := AF_INET; Address.sin_addr := StrToNetAddr('127.0.0.1');
    Address.sin_port := htons(MobilePort);
    FillChar(Packet, SizeOf(Packet), 0);
    FillChar(Packet.Secret, SizeOf(Packet.Secret), Ord('a'));
    Frequency := SDL_GetPerformanceFrequency;
    MobileArm(1, @Receive);
    Send(0); Sleep(20); Send(1);
    Check(Gaps[0] and not Gaps[1], 'Continuous packets must share the initial clock');
    Started := SDL_GetPerformanceCounter;
    MobileSetPaused(true);
    Sleep(45);  { The WebRTC bridge stops forwarding packets while paused. }
    MobileSetPaused(false);
    Sent := SDL_GetPerformanceCounter;
    Send(2);
    Writeln('Observed resumed clock error=', Round((Ends[2] - Sent) * 1000 / Frequency),
      ' ms; discontinuity=', Gaps[2]);
    Check(Gaps[2], 'A pause without arriving packets must break capture continuity');
    Check((Ends[2] >= Sent) and (Ends[2] <= Arrivals[2]),
      'Resumed input retained the pre-pause clock offset');
    Writeln('PASS no-packet pause: ', Round((Sent - Started) * 1000 / Frequency),
      ' ms; resumed clock error=', Round((Ends[2] - Sent) * 1000 / Frequency), ' ms');
    Sleep(20); Send(3);
    Check(not Gaps[3], 'Continuous resumed packets must not repeatedly reset');
    { Both state changes can occur before the receiving thread wakes. }
    MobileSetPaused(true); MobileSetPaused(false); Send(4);
    Check(Gaps[4], 'A pause edge must survive even when the receiver observes only resumed state');
    Writeln('PASS immediate pause/resume preserves the discontinuity');
  finally
    MobileClose; CloseSocket(Sender);
  end;
end.
