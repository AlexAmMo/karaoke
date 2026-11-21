{ Short, opt-in acoustic round-trip test. Only millisecond energy summaries are retained. }
unit UKaraokeCalibration;
{$mode objfpc}{$H+}{$pointermath on}
interface
const CalibrationDurationMs = 4450;
type TCalibrationResult = record
  Success: boolean;
  RoundtripMs, SpreadMs, Samples: integer;
end;
procedure CalibrationStart(NowMs: double; OutputRate: integer);
procedure CalibrationCancel;
function CalibrationActive: boolean;
procedure CalibrationOutput(Data: PSmallInt; Frames, Channels: integer; Rate: double; NowMs: double);
procedure CalibrationInput(Data: PSmallInt; Frames: integer; Rate, NowMs: double);
function CalibrationFinish: TCalibrationResult;
implementation
uses Math;
const
  PulseMs = 32;
  MaxDelayMs = 500;
  Pulses: array[0..6] of integer = (340, 865, 1460, 1980, 2580, 3150, 3730);
var
  Guard: TRTLCriticalSection;
  Active: LongInt;
  Origin: double;
  OutputFrames: Int64;
  Wave: array of SmallInt;
  Emitted: array[0..High(Pulses)] of integer;
  AbsSum: array[0..CalibrationDurationMs] of Int64;
  Count: array[0..CalibrationDurationMs] of integer;
function CalibrationActive: boolean;
begin Result:=InterlockedCompareExchange(Active,0,0)=1; end;
procedure CalibrationStart(NowMs: double; OutputRate: integer);
var I: integer; Phase: double;
begin
  CalibrationCancel;
  EnterCriticalSection(Guard);
  try
    Origin:=NowMs; OutputFrames:=0;
    FillChar(AbsSum,SizeOf(AbsSum),0); FillChar(Count,SizeOf(Count),0);
    for I:=0 to High(Emitted) do Emitted[I]:=-1;
    SetLength(Wave,Max(1,Round(OutputRate*PulseMs/1000)));
    for I:=0 to High(Wave) do
    begin
      Phase:=I/Length(Wave);
      Wave[I]:=Round(2500*Sqr(Sin(Pi*Phase))*Sin(2*Pi*1700*I/OutputRate));
    end;
    InterlockedExchange(Active,1);
  finally LeaveCriticalSection(Guard); end;
end;
procedure CalibrationCancel;
begin
  InterlockedExchange(Active,0);
  { Wait for the previous measurement's callback before reusing its workspace. }
  EnterCriticalSection(Guard); LeaveCriticalSection(Guard);
end;
procedure CalibrationOutput(Data: PSmallInt; Frames, Channels: integer; Rate: double; NowMs: double);
var Pulse,I,C,Start,First,Last,Index: integer;
begin
  if not CalibrationActive then Exit;
  EnterCriticalSection(Guard);
  try
    if not CalibrationActive then Exit;
    for Pulse:=0 to High(Pulses) do
    begin
      Start:=Round(Pulses[Pulse]*Rate/1000)-OutputFrames;
      First:=Max(Start,0); Last:=Min(Frames,Start+Length(Wave));
      if First>=Last then Continue;
      if Emitted[Pulse]<0 then Emitted[Pulse]:=Round(NowMs-Origin+Start*1000/Rate);
      for I:=First to Last-1 do
        for C:=0 to Channels-1 do
        begin
          Index:=I*Channels+C;
          Data[Index]:=EnsureRange(integer(Data[Index])+Wave[I-Start],-32768,32767);
        end;
    end;
    Inc(OutputFrames,Frames);
  finally LeaveCriticalSection(Guard); end;
end;
procedure CalibrationInput(Data: PSmallInt; Frames: integer; Rate, NowMs: double);
var I,Bin: integer; Start,Step: double;
begin
  if not CalibrationActive then Exit;
  Step:=1000/Rate;
  Start:=NowMs-Origin-Frames*Step;
  EnterCriticalSection(Guard);
  try
    if not CalibrationActive then Exit;
    for I:=0 to Frames-1 do
    begin
      Bin:=Floor(Start+I*Step);
      if (Bin<0) or (Bin>High(AbsSum)) then Continue;
      Inc(AbsSum[Bin],Abs(integer(Data[I]))); Inc(Count[Bin]);
    end;
  finally LeaveCriticalSection(Guard); end;
end;
function CalibrationFinish: TCalibrationResult;
var E: array[0..CalibrationDurationMs] of double;
    Candidate,Votes: array[0..High(Pulses)] of integer;
    I,J,K,D,T,First,Good,Center: integer;
    Baseline,Peak,A,B,Cross,Score,Best,Shape,Mean,Width: double;
begin
  CalibrationCancel;
  Result:=Default(TCalibrationResult);
  for I:=0 to High(E) do
    if Count[I]>0 then E[I]:=AbsSum[I]/Count[I] else E[I]:=0;
  for I:=0 to High(Pulses) do
  begin
    Candidate[I]:=-1;
    if (Emitted[I]<0) or (Emitted[I]+MaxDelayMs+PulseMs>=High(E)) then Continue;
    Best:=0;
    for D:=0 to MaxDelayMs do
    begin
      First:=Emitted[I]+D;
      if First<20 then Continue;
      Baseline:=0; Peak:=0; Mean:=0;
      for K:=First-16 to First-1 do Baseline:=Baseline+E[K]/16;
      for K:=0 to PulseMs-1 do
      begin Peak:=Max(Peak,E[First+K]); Mean:=Mean+E[First+K]/PulseMs; end;
      if (Peak<Baseline*1.8+10) or (Mean<Baseline+8) then Continue;
      A:=0; B:=0; Cross:=0;
      for K:=0 to PulseMs-1 do
      begin
        Shape:=Sqr(Sin(Pi*(K+0.5)/PulseMs))-0.5;
        Width:=E[First+K]-Mean;
        Cross:=Cross+Shape*Width; A:=A+Sqr(Shape); B:=B+Sqr(Width);
      end;
      if B=0 then Continue;
      Score:=Cross/Sqrt(A*B);
      if (Score>0.78) and (Score>Best) then begin Best:=Score; Candidate[I]:=D; end;
    end;
  end;
  Good:=0; Center:=-1;
  for I:=0 to High(Candidate) do if Candidate[I]>=0 then
  begin
    T:=0;
    for J:=0 to High(Candidate) do if (Candidate[J]>=0) and (Abs(Candidate[J]-Candidate[I])<=15) then Inc(T);
    if T>Good then begin Good:=T; Center:=Candidate[I]; end;
  end;
  if Good<5 then Exit;
  J:=0;
  for I:=0 to High(Candidate) do if (Candidate[I]>=0) and (Abs(Candidate[I]-Center)<=15) then
  begin Votes[J]:=Candidate[I]; Inc(J); end;
  for I:=1 to Good-1 do
  begin
    T:=Votes[I]; J:=I;
    while (J>0) and (Votes[J-1]>T) do begin Votes[J]:=Votes[J-1]; Dec(J); end;
    Votes[J]:=T;
  end;
  Result.Success:=true; Result.Samples:=Good;
  Result.RoundtripMs:=Votes[Good div 2]; Result.SpreadMs:=Votes[Good-1]-Votes[0];
end;
initialization InitCriticalSection(Guard);
finalization DoneCriticalSection(Guard);
end.
