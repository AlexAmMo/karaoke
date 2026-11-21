{ Exercise the production SDL PCM stream without a microphone or output device. }
program test_pcm_conversion;
{$mode delphi}{$H+}
uses SysUtils, Math, SDL2, UKaraokePCM;
type TSamples = array of SmallInt;
procedure Check(OK: Boolean; const Msg: String);
begin if not OK then raise Exception.Create(Msg); end;

function Convert(const Input: TSamples; InputHz, InputChannels, OutputHz: Integer; Chunked: Boolean): TSamples;
const Chunks: array[0..5] of Integer = (17, 511, 96, 4096, 257, 23);
var Stream: TKaraokePCM; Frames, At, K, N: Integer; Dest: TSamples;
  procedure Drain;
  var Bytes, Count, Start: Integer;
  begin
    Bytes := Stream.Available;
    Check((Bytes >= 0) and (Bytes mod 4 = 0), 'Bad stereo frame boundary');
    if Bytes = 0 then Exit;
    Start := Length(Dest);
    SetLength(Dest, Start + Bytes div 2 + 2);
    Dest[Start + Bytes div 2] := 12345;
    Count := Stream.Read(@Dest[Start], Bytes);
    Check((Count = Bytes) and (Dest[Start + Count div 2] = 12345), 'Output exceeded supplied capacity');
    SetLength(Dest, Start + Count div 2);
  end;
begin
  Stream := TKaraokePCM.Create(AUDIO_S16SYS, InputChannels, InputHz, AUDIO_S16SYS, 2, OutputHz);
  try
    Check(Stream.Ready, 'Open stream: '+SDL_GetError);
    Frames := Length(Input) div InputChannels; At := 0; K := 0;
    while At < Frames do
    begin
      N := Frames - At;
      if Chunked then N := Min(N, Chunks[K mod Length(Chunks)]);
      Check(Stream.Push(@Input[At*InputChannels], N*InputChannels*2), 'Push');
      Drain; Inc(At,N); Inc(K);
    end;
    Check(Stream.Finish, 'Flush'); Drain;
    Check(Stream.Finish and (Stream.Available=0), 'Repeated flush produced a tail');
    Check(Stream.Push(@Input[0], 2*InputChannels), 'Queue before seeking');
    Stream.Clear;
    Check(not Stream.Finished and (Stream.Available=0), 'Seek retained old audio');
    Result := Dest;
  finally Stream.Free; end;
end;

var Input, Whole, Cut: TSamples; I, N, Crossings, MaxJump, MaxDiff: Integer;
begin
  SetLength(Input, 65536);
  for I := 0 to High(Input) do Input[I] := I - 32768;
  Cut := Convert(Input,48000,1,48000,true);
  Check(Length(Cut) = 2*Length(Input), '48 kHz upmix frame count');
  for I := 0 to High(Input) do Check((Cut[2*I]=Input[I]) and (Cut[2*I+1]=Input[I]), 'Mono sample changed: '+IntToStr(I));
  Cut := Convert(Input,48000,2,48000,true);
  Check(Length(Cut)=Length(Input), 'Stereo frame count');
  for I := 0 to High(Input) do Check(Cut[I]=Input[I], 'Stereo sample changed');
  N := 2*44100; SetLength(Input,N);
  for I:=0 to N-1 do Input[I]:=Round(12000*Sin(2*Pi*440*I/44100));
  Whole:=Convert(Input,44100,1,48000,false); Cut:=Convert(Input,44100,1,48000,true);
  Check((Abs(Length(Cut) div 2 - 96000)<=1) and (Length(Whole)=Length(Cut)),'44.1k to 48k frame count: '+IntToStr(Length(Cut) div 2));
  Crossings:=0; MaxJump:=0; MaxDiff:=0;
  for I:=1 to Length(Cut) div 2-1 do
  begin
    if (Cut[2*(I-1)]<=0) and (Cut[I*2]>0) then Inc(Crossings);
    MaxJump:=Max(MaxJump,Abs(Cut[2*I]-Cut[2*(I-1)]));
    MaxDiff:=Max(MaxDiff,Abs(Cut[2*I]-Whole[2*I]));
  end;
  Check((Abs(Crossings-880)<=1) and (MaxJump<1500) and (MaxDiff<16),'Discontinuous output or pitch drift');
  WriteLn('PASS 65536 exact mono samples on both channels; stereo identity; 44.1→48 kHz frames=',Length(Cut) div 2,
          ' cycles=',Crossings,' max_chunk_difference=',MaxDiff,' max_delta=',MaxJump,'; seek and EOF');
end.
