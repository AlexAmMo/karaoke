{ Timestamped mono capture for scoring. The caller serializes access. GPL-3.0-only. }
unit UKaraokeCaptureHistory;
{$mode delphi}{$H+}
interface

type
  TDeviceCaptureClock = record
    private
      Anchored: Boolean;
      DeviceOrigin, PreviousDeviceTime: Double;
      HostOrigin: Int64;
    public
      procedure Reset;
      function Align(Received, TickRate: Int64; DeviceEnd: Double; var Gap: Boolean): Int64;
  end;

  TCaptureHistory = class
    private type
      TBlock = record
        EndTick: Int64;
        FirstFrame, EndFrame, RunStart: Int64;
      end;
    private
      Samples: array[0..131071] of SmallInt;
      Blocks: array[0..2047] of TBlock;
      NextBlock, BlockCount: Integer;
      TotalFrames, Frequency: Int64;
      SampleRate: Double;
      function TicksFor(Frames: Int64): Int64;
    public
      procedure Reset(ClockFrequency: Int64; Rate: Double);
      procedure Append(Data: PSmallInt; Frames: Integer; EndTick: Int64; Interrupted: Boolean);
      function Window(EndTick: Int64; Output: PSmallInt; Frames: Integer): Boolean;
  end;

implementation
uses Math;

procedure TDeviceCaptureClock.Reset;
begin
  Anchored := False;
  DeviceOrigin := 0;
  PreviousDeviceTime := 0;
  HostOrigin := 0;
end;

function TDeviceCaptureClock.Align(Received, TickRate: Int64; DeviceEnd: Double; var Gap: Boolean): Int64;
var Estimate, Phase: Int64; Interval: Double;
begin
  Result := Received;
  if (TickRate <= 0) or (DeviceEnd <= 0) or IsNan(DeviceEnd) or IsInfinite(DeviceEnd) then
  begin
    Gap := Gap or Anchored;
    Reset;
    Exit;
  end;
  Interval := DeviceEnd - PreviousDeviceTime;
  if Anchored and not Gap and (Interval > 0) and (Interval < 0.250) then
  begin
    Estimate := HostOrigin + Round((DeviceEnd - DeviceOrigin) * TickRate);
    Phase := Received - Estimate;
    if Abs(Phase) < TickRate div 10 then
    begin
      { Follow slow clock drift without copying callback scheduling jitter.
        Both clocks retain the existing calibrated delivery-time reference. }
      Inc(HostOrigin, Round(EnsureRange(Phase, -TickRate div 100, TickRate div 100) * (Interval / 3)));
      Result := HostOrigin + Round((DeviceEnd - DeviceOrigin) * TickRate);
      PreviousDeviceTime := DeviceEnd;
      Exit;
    end;
  end;
  Gap := Gap or Anchored;
  DeviceOrigin := DeviceEnd;
  PreviousDeviceTime := DeviceEnd;
  HostOrigin := Received;
  Anchored := True;
end;

procedure TCaptureHistory.Reset(ClockFrequency: Int64; Rate: Double);
begin
  Frequency := ClockFrequency;
  SampleRate := Rate;
  NextBlock := 0;
  BlockCount := 0;
  TotalFrames := 0;
end;

function TCaptureHistory.TicksFor(Frames: Int64): Int64;
begin
  Result := Round(Frames * (Frequency / SampleRate));
end;

procedure TCaptureHistory.Append(Data: PSmallInt; Frames: Integer; EndTick: Int64; Interrupted: Boolean);
var Previous, Start, Count: Integer; Block: TBlock;
begin
  if (Frames <= 0) or (Frames > Length(Samples)) or (Frequency <= 0) or (SampleRate <= 0) then Exit;
  Block.FirstFrame := TotalFrames;
  Block.EndFrame := TotalFrames + Frames;
  Block.EndTick := EndTick;
  Block.RunStart := TotalFrames;
  if (BlockCount > 0) and not Interrupted then
  begin
    Previous := (NextBlock - 1) and High(Blocks);
    { Host callback timestamps can jitter. A missed interval starts a new run,
      so an analysis window cannot join samples from opposite sides of a gap. }
    if (EndTick > Blocks[Previous].EndTick) and
       (Abs(EndTick - Blocks[Previous].EndTick - TicksFor(Frames)) <=
        Max(Frequency * 12 div 1000, TicksFor(Frames) div 2)) then
      Block.RunStart := Blocks[Previous].RunStart;
  end;
  Start := TotalFrames and High(Samples);
  Count := Min(Frames, Length(Samples) - Start);
  Move(Data^, Samples[Start], Count * SizeOf(SmallInt));
  if Count < Frames then Move((Data + Count)^, Samples[0], (Frames - Count) * SizeOf(SmallInt));
  Blocks[NextBlock] := Block;
  NextBlock := (NextBlock + 1) and High(Blocks);
  BlockCount := Min(Length(Blocks), BlockCount + 1);
  TotalFrames := Block.EndFrame;
end;

function TCaptureHistory.Window(EndTick: Int64; Output: PSmallInt; Frames: Integer): Boolean;
var I, Index, Start, Count: Integer; Age, EndFrame: Int64; Block: TBlock;
begin
  Result := False;
  if (Frames <= 0) or (Frames > Length(Samples)) then Exit;
  for I := 1 to BlockCount do
  begin
    Index := (NextBlock - I) and High(Blocks);
    Block := Blocks[Index];
    Age := Block.EndTick - EndTick;
    if Age < 0 then
    begin
      { The current beat can fall in the partial callback that the device has
        not delivered yet. Accept only one short in-flight block. }
      if I = 1 then
      begin
        if -Age > Min(Frequency div 25, TicksFor(Block.EndFrame - Block.FirstFrame) +
           Frequency div 200) then Exit;
      end
      else if Blocks[(Index + 1) and High(Blocks)].RunStart <> Block.RunStart then Exit;
      EndFrame := Block.EndFrame;
    end
    else
    begin
      if Age > TicksFor(Block.EndFrame - Block.FirstFrame) then Continue;
      EndFrame := Block.EndFrame - Round(Age * (SampleRate / Frequency));
    end;
    if (EndFrame - Frames < Block.RunStart) or (EndFrame - Frames < TotalFrames - Length(Samples)) then Exit;
    Start := (EndFrame - Frames) and High(Samples);
    Count := Min(Frames, Length(Samples) - Start);
    Move(Samples[Start], Output^, Count * SizeOf(SmallInt));
    if Count < Frames then Move(Samples[0], (Output + Count)^, (Frames - Count) * SizeOf(SmallInt));
    Exit(True);
  end;
end;
end.
