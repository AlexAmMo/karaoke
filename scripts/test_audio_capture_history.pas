{ Deterministic regressions for device routing and the capture timeline used by the scorer. }
program test_audio_capture_history;
{$mode delphi}{$H+}
uses SysUtils, Math, UKaraokeCaptureHistory, UKaraokeOutput;

const Rate = 48000; FramesPerBlock = 240; FramesPerNote = 4800;
      TestNotes = 300; WindowSize = 2048;
var Clock: TDeviceCaptureClock; Gap: Boolean; Aligned: Int64; History: TCaptureHistory; Block: array[0..FramesPerBlock-1] of SmallInt;
    NoteWindow: array[0..WindowSize-1] of SmallInt;
    Frame, RenderFrame, Note, I, LastNote, HistoryHits, LatestHits, Marker, Offset: Integer;

procedure Check(Value: Boolean; const MessageText: String);
begin
  if not Value then raise Exception.Create(MessageText);
end;

procedure CheckDuplexProfile;
const BuiltInInput = 'coreaudio:BuiltInMicrophoneDevice';
      BuiltInOutput = 'coreaudio:BuiltInSpeakerDevice';
      Hardware = 'Mac16,1';
begin
  Check(PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, '',
    Rate, true, true), 'Validated built-in pair must use the measured profile');
  Check(PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, '10ms-64',
    Rate, true, true), 'Explicit measured profile');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, 'published',
    Rate, true, true), 'Original profile requested');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, 'typo',
    Rate, true, true), 'Unknown profile uses original parameters');
  Check(not PreferShortDuplex('wasapi', Hardware, BuiltInInput, BuiltInOutput, '',
    Rate, true, true), 'Backend must match');
  Check(not PreferShortDuplex('coreaudio', 'Mac16,2', BuiltInInput, BuiltInOutput, '',
    Rate, true, true), 'Model must match');
  Check(not PreferShortDuplex('coreaudio', Hardware, 'USB Mic', BuiltInOutput, '',
    Rate, true, true), 'Preserve USB input settings');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, 'AirPods', '',
    Rate, true, true), 'Preserve other output settings');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, '',
    44100, true, true), 'Unsupported sample rate');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, '',
    Rate, false, true), 'Custom input or single device');
  Check(not PreferShortDuplex('coreaudio', Hardware, BuiltInInput, BuiltInOutput, '',
    Rate, true, false), 'Explicit input latency must be honoured');
  Writeln('PASS native duplex selection for validated hardware, custom settings and fallback');
end;

function Frequency(N: Integer): Double;
begin
  if Odd(N) then Result := 659.255 else Result := 440;
end;

function Matches(N: Integer): Boolean;
var J, Crossings: Integer; Observed: Double;
begin
  Crossings := 0;
  for J := 1 to High(NoteWindow) do
    if (NoteWindow[J-1] <= 0) and (NoteWindow[J] > 0) then Inc(Crossings);
  Observed := Crossings * Rate / Length(NoteWindow);
  Result := Abs(Observed - Frequency(N)) < 30;
end;

begin
  CheckDuplexProfile;
  Clock.Reset; Gap := False;
  Check(Clock.Align(86400000000, 1000000, 1234, Gap) = 86400000000, 'Clock epoch mismatch');
  Aligned := Clock.Align(86400022000, 1000000, 1234.010, Gap);
  Check(not Gap and (Abs(Aligned - 86400010000) < 50), 'Callback jitter shifted captured samples');
  Aligned := Clock.Align(86400030000, 1000000, 1234.020, Gap);
  Check(not Gap and (Abs(Aligned - 86400020000) < 100), 'Scheduling jitter persisted');
  Aligned := Clock.Align(86400031000, 1000000, 1234.040, Gap);
  Check(not Gap and (Abs(Aligned - 86400040000) < 150), 'Early delivery squashed media time');
  Aligned := Clock.Align(86400040000, 1000000, 2, Gap);
  Check(Gap and (Aligned = 86400040000), 'Restarted device clock reused its old offset');
  History := TCaptureHistory.Create;
  try
    History.Reset(Rate, Rate);  { one tick per frame; the ring wraps many times }
    Frame := 0; LastNote := -1; RenderFrame := 11520;
    while Frame < TestNotes*FramesPerNote do
    begin
      for I := 0 to High(Block) do
        Block[I] := Round(12000 * Sin(2*Pi*Frequency((Frame+I) div FramesPerNote)*(Frame+I)/Rate));
      Inc(Frame, FramesPerBlock);
      History.Append(@Block[0], FramesPerBlock, Frame, False);
      if (Frame < RenderFrame) and (Frame < TestNotes * FramesPerNote) then Continue;
      while LastNote < TestNotes-1 do
      begin
        Note := LastNote+1;
        Marker := Note * FramesPerNote + FramesPerNote div 2;
        if Marker > Frame then Break;
        Check(History.Window(Marker, @NoteWindow[0], WindowSize), 'Missing historical window');
        if Matches(Note) then Inc(HistoryHits);
        Check(History.Window(Frame, @NoteWindow[0], WindowSize), 'Missing latest window');
        if Matches(Note) then Inc(LatestHits);
        LastNote := Note;
      end;
      Inc(RenderFrame, 11520); { 240 ms presentation stalls }
    end;
    Check(HistoryHits = TestNotes, 'Wrong note scored across a frame stall');
    Check(LatestHits < TestNotes * 0.8, 'Latest-only control must reproduce the regression');
    Check(not History.Window(2400, @NoteWindow[0], WindowSize), 'Overwritten audio reused');
    Check(not History.Window(Frame + Rate, @NoteWindow[0], WindowSize), 'Expired audio reused');
    { A missed 5 ms block and a real disconnected interval cannot be stitched together. }
    for Offset := 0 to 1 do
    begin
      if Offset = 1 then Inc(Frame, Rate);
      Inc(Frame, FramesPerBlock); History.Append(@Block[0], FramesPerBlock, Frame, Offset = 0);
      Check(not History.Window(Frame, @NoteWindow[0], WindowSize), 'Window crossed a capture gap');
      for I := 1 to 10 do
      begin Inc(Frame, FramesPerBlock); History.Append(@Block[0], FramesPerBlock, Frame, False); end;
      Check(History.Window(Frame, @NoteWindow[0], WindowSize), 'Capture did not recover');
    end;
    History.Reset(Rate, 44100);
    Check(not History.Window(Frame, @NoteWindow[0], WindowSize), 'Prior route survived reset');
    Writeln('PASS ', TestNotes, ' alternating notes, 240 ms renderer interval: historical=', HistoryHits,
      ', latest-only=', LatestHits, '; wrap, dropped block, gap, reset');
  finally History.Free; end;
end.
