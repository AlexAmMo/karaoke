{ Deterministic loopback at known delays through the same pulse emitter and estimator used on stage. }
program TestAudioCalibration;
{$mode objfpc}{$H+}
uses SysUtils, Math, UKaraokeCalibration;
procedure Exercise(Rate, DelayMs, Mode: integer);
const Frames = 256;
var Loopback: array of SmallInt;
    Input, Output: array[0..Frames-1] of SmallInt;
    Result: TCalibrationResult;
    N,J,Source: integer;
begin
  SetLength(Loopback,Round((CalibrationDurationMs+100)*Rate/1000));
  CalibrationStart(0,Rate);
  N:=0; RandSeed:=104729;
  while N+Frames<=Length(Loopback) do
  begin
    FillChar(Output,SizeOf(Output),0);
    CalibrationOutput(@Output[0],Frames,1,Rate,N*1000.0/Rate);
    Move(Output[0],Loopback[N],SizeOf(Output));
    for J:=0 to Frames-1 do
    begin
      Source:=N+J-Round(DelayMs*Rate/1000);
      Input[J]:=0;
      if Mode>0 then Input[J]:=Random(160)-80;
      if (Mode=2) and (Source>=0) then Inc(Input[J],Loopback[Source] div 3);
    end;
    CalibrationInput(@Input[0],Frames,Rate,(N+Frames)*1000.0/Rate);
    Inc(N,Frames);
  end;
  Result:=CalibrationFinish;
  if Mode=2 then begin
    if not Result.Success or (Abs(Result.RoundtripMs-DelayMs)>2) or (Result.Samples<>7) then Halt(1);
    WriteLn('PASS ',Rate,' Hz delay ',DelayMs,': measured ',Result.RoundtripMs,' ms, spread ',Result.SpreadMs,' ms');
  end else begin
    if Result.Success then Halt(1);
    WriteLn('PASS insufficient signal rejected (mode ',Mode,')');
  end;
end;
const Rates: array[0..1] of integer = (441,480);
var Rate: integer;
begin
  if Abs((CalibrationClockMs(1728000001000000,1000000000)-CalibrationClockMs(1728000000000000,1000000000))-1)>0.00001 then Halt(1);
  for Rate in Rates do begin
    Exercise(Rate*100,0,2); Exercise(Rate*100,50,2); Exercise(Rate*100,100,2); Exercise(Rate*100,200,2);
    Exercise(Rate*100,0,0); Exercise(Rate*100,0,1);
  end;
end.
