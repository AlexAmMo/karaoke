{ Karaoke native shell. GPL-3.0-only. JSON is exchanged only in a private local directory. }
unit UKaraokeShell;
{$mode delphi}{$H+}{$codepage UTF8}
interface
uses sdl2;
function ShellEnabled: boolean;
function ShellSynthetic: boolean;
procedure ShellTick;
procedure ShellDraw;
procedure ShellViewport;
procedure ShellFinishFrame;
procedure ShellGroupLabel(X,Y,W,Singer: integer);
procedure ShellDrawPitchTrace(Left, Top, Width: real; Track, Singer, Spacing: integer);
function ShellEvent(var Event: TSDL_Event): boolean;
procedure ShellCaptureStart;
procedure ShellCaptureStop;
implementation
uses UKaraokePalette, SysUtils, Classes, Math, fpjson, jsonparser, UGraphic, UDisplay, URenderer,
  UText, UIni, USongs, USong, UPath, UMusic, URecord, UNote, UScreenMain, UScreenSong,
  UKaraokeOutput, UKaraokeCalibration, UKaraokeMobileAudio, UCommon, UPathUtils, UScreenSingController, UScreenScore, UThemes, UAvatars;
function SDL_GetDefaultAudioInfo(var Name: PAnsiChar; Spec: PSDL_AudioSpec; Capture: integer): integer; cdecl; external SDL_LibName name 'SDL_GetDefaultAudioInfo';
procedure SDL_free(mem: pointer); cdecl; external SDL_LibName name 'SDL_free';
var
  Started: boolean = false;
  Quitting: boolean = false;
  View: TJSONObject = nil;
  LastStatus, LastView: cardinal;
  Focus: integer = -1;
  Scroll: integer = 0;
  EditValue, EditAction, Page, ErrorText, Token: UTF8String;
  StartFailureToken, StartFailureAttempt, StartFailureMessage: UTF8String;
  EditSelectedAll: boolean = false;
  LastSubmitted, Composition: UTF8String;
  LastEditTick: cardinal;
  Sequence: integer = 0;
  SynthPosition: int64 = 0;
  SynthTick: cardinal;
  ProbePending, ProbeMatched: array[0..KaraokeMaxSingers-1] of boolean;
  ProbeClass, ProbeFirstMs, ProbeConfirmMs: array[0..KaraokeMaxSingers-1] of integer;
  ProbeStart: array[0..KaraokeMaxSingers-1] of cardinal;
  SynthPattern: array[0..KaraokeMaxSingers-1] of boolean;
  SynthDelayMs: array[0..KaraokeMaxSingers-1] of integer;
  SynthFrequency: array[0..KaraokeMaxSingers-1] of double;
  SynthFeeding, MobileSlot: array[0..KaraokeMaxSingers-1] of boolean;
  CaptureActive: boolean;
  SavedChannels: array of array of integer;
  CaptureCount: integer;
  ActiveMobileSecret: RawByteString;
  CalibrationState, CalibrationMessage: UTF8String;
  CalibrationStarted, OutputChecked: cardinal;
  OutputName, CalibrationInputName, CalibrationOutputName: UTF8String;
  CalibrationDevice, CalibrationChannel, CalibrationOutputRate: integer;
  CalibrationDirect: boolean;
  CalibrationResult: TCalibrationResult;
  CaptureTestFrame: boolean;
  Gains: array[0..KaraokeMaxSingers-1] of single;
  Hover: integer = -1;
  PendingForget: TStringList;
  TestingInput: boolean = false;
  LastMouseX, LastMouseY, MouseClicks: integer;
  LastAction: string;
  PanelCollapsed: boolean = false;
  PanelHover: boolean = false;
  PanelToggleFocused: boolean = false;
  StageFocused: boolean = false;
  AddFocused: boolean = false;
  KeyboardFocusVisible: boolean = true;
  HeldAdd, HoverAdd, PendingAdd, PendingAddToken, ConfirmedAdd: string;
  ConfirmedAt: cardinal;
  ResultsDismissed: boolean = false;
  CoverTimes: array[0..31] of qword;
  CoverUse: qword = 0;
  CoverPaths: array[0..31] of string;
  CoverTextures: array[0..31] of TTexture;

const
  TraceColumns = 720; // native note lane width in theme coordinates
  NoPitch = -128;
type
  TPitchTrace = record
    Active: boolean;
    Phrase: integer;
    LastBeat: real;
    LastTick: cardinal;
    Column, Offset: integer;
    Samples: array[0..TraceColumns-1] of shortint;
  end;
var
  PitchTraces: array[0..KaraokeMaxSingers-1] of TPitchTrace;

function Root: string;
begin Result:=GetEnvironmentVariable('KARAOKE_IPC'); end;
function ShellEnabled: boolean;
begin Result:=Root<>''; end;
function ShellSynthetic: boolean;
begin Result:=ShellEnabled and (GetEnvironmentVariable('KARAOKE_TEST_INPUT')='1'); end;
function Singing: boolean;
begin Result:=Assigned(ScreenSing) and Assigned(Display.CurrentScreen) and (Display.CurrentScreen^=ScreenSing); end;
function FocusAction: string;
begin
  Result:='';
  case Focus of
    -12: Result:='stage';
    -11: Result:='panel';
    -10: if Assigned(View) and (View.Get('undo','')<>'') then Result:='undo:'+View.Get('undo','');
    -9: Result:='page:Buscar';
    -8: Result:='page:Cola';
    -7: Result:='page:Ajustes';
    -6: if Singing then Result:='pause';
    -5: if Singing then Result:='end';
  end;
  if (Focus>=0) and Assigned(View) and (Focus<View.Arrays['rows'].Count) then
  begin
    Result:=TJSONObject(View.Arrays['rows'][Focus]).Get('action','');
    if AddFocused or (Result='') then Result:=TJSONObject(View.Arrays['rows'][Focus]).Get('add_action','');
  end;
end;
function ExpandedSideWidth: integer;
begin Result:=Round(EnsureRange(ScreenW*0.34,340.0,440.0)); end;
function SideWidth: integer;
begin if PanelCollapsed then Result:=0 else Result:=ExpandedSideWidth; end;
function Height: single;
begin Result:=ScreenH*400/ExpandedSideWidth; end;
procedure PublishSearch; forward;
procedure SetPanelCollapsed(Collapsed: boolean);
begin
  if PanelCollapsed=Collapsed then Exit;
  HeldAdd:=''; HoverAdd:='';
  PanelCollapsed:=Collapsed; PanelHover:=false; Hover:=-1; StageFocused:=false;
  // Hiding the panel is not submitting/cancelling an edit. Keep its value and
  // action-based focus while suspending text input until it becomes visible.
  if PanelCollapsed then
  begin if Composition='' then PublishSearch; PanelToggleFocused:=true; SDL_StopTextInput; LastAction:='panel:hide'; end
  else
  begin
    PanelToggleFocused:=false; StageFocused:=Focus=-12; LastAction:='panel:show';
    if EditAction<>'' then SDL_StartTextInput;
  end;
end;
procedure SaveJSON(const Name: string; Value: TJSONData);
var SL: TStringList; Temp: string;
begin
  SL:=TStringList.Create;
  try
    SL.Text:=Value.AsJSON; Temp:=Name+'.tmp'; SL.SaveToFile(Temp);
    {$IFDEF MSWINDOWS}DeleteFile(Name);{$ENDIF}
    RenameFile(Temp,Name);
  finally SL.Free; end;
end;
function ReadJSON(const Name: string): TJSONObject;
var SL: TStringList;
begin
  Result:=nil; SL:=TStringList.Create;
  try
    SL.LoadFromFile(Name); Result:=TJSONObject(GetJSON(SL.Text));
  finally SL.Free; end;
end;
procedure Emit(const Action: string; const Value: string='');
var J: TJSONObject;
begin
  Inc(Sequence); LastAction:=Action; J:=TJSONObject.Create;
  try
    J.Add('action',Action); J.Add('value',Value);
    SaveJSON(Root+'/events/'+Format('%.10d-%.8d',[SDL_GetTicks,Sequence])+'.json',J);
  finally J.Free; end;
end;
function AddAction(const Action: string): boolean;
begin
  Result:=(Action='enqueue') or (Pos('enqueue:',Action)=1) or
    (Pos('result:best:',Action)=1) or (Pos('result:queue:',Action)=1) or
    (Pos('result:obtain:',Action)=1);
end;
function RowAddKey(const Action: string): string;
begin Result:=Page+'/'+Action; end;
procedure RequestAdd(const Action,Control: string);
var ID:TGUID;
begin
  if not AddAction(Action) then Exit;
  if CreateGUID(ID)<>0 then Exit;
  PendingAddToken:=GUIDToString(ID);
  PendingAdd:=Control; ConfirmedAdd:='';
  Emit(Action,PendingAddToken);
end;
function AddConfirmed(const Control: string): boolean;
begin Result:=(Control<>'') and (ConfirmedAdd=Control) and (SDL_GetTicks-ConfirmedAt<1000); end;
function AddHeld(const Control: string): boolean;
begin Result:=(Control<>'') and (HeldAdd=Control) and (HoverAdd=Control); end;

{ Capture uses the same delayed song clock and pitch detector as Deluxe. The
  ribbon is presentation-only; Player.Note remains entirely owned by scoring. }
procedure ShellDrawPitchTrace(Left, Top, Width: real; Track, Singer, Spacing: integer);
var
  Line: PLine;
  Trace: ^TPitchTrace;
  Span, Phrase, Column, Pitch, Anchor, Offset, I, First, Count: integer;
  Beat, StartX, EndX, Y, ColumnWidth: real;
  Tick: cardinal;
  Parts: TQuadList;
  R,G,B: single;

  procedure AddQuad(X, RowY, SizeX, H, Red, Green, Blue, Alpha: single);
  begin
    if Count = Length(Parts) then SetLength(Parts, Max(16, Count*2));
    Parts[Count].X := X; Parts[Count].Y := RowY;
    Parts[Count].W := SizeX; Parts[Count].H := H;
    Parts[Count].ColR := Red; Parts[Count].ColG := Green; Parts[Count].ColB := Blue;
    Parts[Count].Alpha := Alpha;
    Inc(Count);
  end;

  procedure Ribbon(X1, X2: real; Steps: integer);
  begin
    Y := Top - Steps*Spacing/2;
    AddQuad(X1,Y-2.5,X2-X1,5,0.025,0.08,0.14,0.50);
    AddQuad(X1,Y-1.6,X2-X1,3.2,R,G,B,0.64);
  end;

begin
  if (Singer < 0) or (Singer > High(PitchTraces)) then Exit;
  Phrase := CurrentSong.Tracks[Track].CurrentLine;
  Line := @CurrentSong.Tracks[Track].Lines[Phrase];
  if not Line^.HasLength(Span) then Exit;
  Trace := @PitchTraces[Singer];
  Beat := LyricsState.MidBeatD - GetMidBeat(AudioInputProcessor.Sound[Singer].RouteDelayMs / 1000.0);
  Tick := SDL_GetTicks;
  if not Trace^.Active or (Trace^.Phrase <> Phrase) or (Beat < Trace^.LastBeat-0.01) then
  begin
    FillChar(Trace^.Samples,SizeOf(Trace^.Samples),Byte(128));
    Trace^.Active := true;
    Trace^.Phrase := Phrase;
    Trace^.Column := -1;
    Trace^.Offset := NoPitch;
    Trace^.LastTick := Tick-32;
  end;

  if not ScreenSing.Paused and (Tick-Trace^.LastTick >= 32) then
  begin
    if Beat < Line^.Notes[0].StartBeat then Column := -1
    else if Beat >= Line^.EndBeat then Column := TraceColumns
    else Column := Trunc((Beat-Line^.Notes[0].StartBeat)*TraceColumns/Span);
    if (Trace^.Offset <> NoPitch) and (Trace^.Column >= 0) and (Trace^.Column < TraceColumns)
      and (Column > Trace^.Column) and (Tick-Trace^.LastTick <= 160) then
      FillChar(Trace^.Samples[Trace^.Column],Column-Trace^.Column,Byte(Trace^.Offset));
    Pitch := AudioInputProcessor.Sound[Singer].DetectedPitch;
    if ProbePending[Singer] then
    begin
      if (Pitch>=0) and (Pitch mod 12=ProbeClass[Singer]) then
      begin
        if ProbeMatched[Singer] then
        begin ProbeConfirmMs[Singer]:=Tick-ProbeStart[Singer]; ProbePending[Singer]:=false; end
        else begin ProbeMatched[Singer]:=true; ProbeFirstMs[Singer]:=Tick-ProbeStart[Singer]; end;
      end
      else begin ProbeMatched[Singer]:=false; ProbeFirstMs[Singer]:=-1; end;
    end;
    Offset := NoPitch;
    if Pitch >= 0 then
    begin
      { Keep octave equivalence with the scorer. In a rest, retain the pitch
        frame of the previous note so a sustained voice stays level. }
      Anchor := Line^.Notes[0].Tone;
      for I := 1 to Line^.HighNote do
      begin
        if Line^.Notes[I].StartBeat > Beat then Break;
        Anchor := Line^.Notes[I].Tone;
      end;
      Pitch := Pitch mod 12;
      Offset := (Pitch - Anchor) mod 12;
      if Offset > 6 then Dec(Offset,12);
      if Offset < -6 then Inc(Offset,12);
      Offset := EnsureRange(Anchor + Offset - Line^.BaseNote,-4,19);
      if (Column >= 0) and (Column < TraceColumns) then Trace^.Samples[Column] := Offset;
    end;
    Trace^.LastBeat := Beat;
    Trace^.LastTick := Tick;
    Trace^.Column := Column;
    Trace^.Offset := Offset;
  end;

  if not Odd(Singer) then begin R := 1.0; G := 0.694; B := 0.541; end
  else begin R := 0.675; G := 0.945; B := 0.804; end;
  ColumnWidth := Width / TraceColumns;
  Count := 0;
  I := 0;
  while I < TraceColumns do
  begin
    First := I;
    Offset := Trace^.Samples[I];
    repeat Inc(I) until (I = TraceColumns) or (Trace^.Samples[I] <> Offset);
    if Offset <> NoPitch then Ribbon(Left+First*ColumnWidth,Left+I*ColumnWidth,Offset);
  end;
  { A short head is visible as soon as a voice is detected, including before
    or after the phrase's horizontal time span. Never extend past the lane. }
  if Trace^.Offset <> NoPitch then
  begin
    EndX := EnsureRange(Left+(Trace^.Column+1)*ColumnWidth,Left+6,Left+Width);
    StartX := EndX-6;
    Ribbon(StartX,EndX,Trace^.Offset);
  end;
  SetLength(Parts,Count);
  if Count > 0 then Renderer.DrawQuads(Parts);
end;

procedure ShellFinishFrame;
var Previous: IPath;
begin
  if not CaptureTestFrame then Exit;
  CaptureTestFrame := false;
  Previous := ScreenshotsPath;
  try
    ScreenshotsPath := Path(Root);
    Display.SaveScreenShot(false);
  finally
    ScreenshotsPath := Previous;
  end;
end;

procedure RestoreRoutes;
var D: integer;
begin
  for D:=0 to High(SavedChannels) do
    Ini.InputDeviceConfig[D].ChannelToPlayerMap:=SavedChannels[D];
  SetLength(SavedChannels,0);
end;

function InstallRoutes(J: TJSONObject; N: integer): boolean;
type TRoute = record Device, Channel: integer; Mobile: boolean; Gain: single; DelayMs: integer; end;
var R: array[0..KaraokeMaxSingers-1] of TRoute;
    Routes: TJSONArray; Entry: TJSONObject; I,K,D,C,Config: integer; HasMobile: boolean;
begin
  Result:=false; HasMobile:=false; KaraokeHasRouteDelay:=false;
  if not Assigned(J.Find('routes')) then
  begin
    // Historical turns can use the persistent Deluxe bindings.
    for I:=0 to N-1 do
    begin
      MobileSlot[I]:=false; AudioInputProcessor.Sound[I].RouteDelayMs:=0;
      AudioInputProcessor.Sound[I].MonitorGain:=Gains[I];
    end;
    Exit(ShellSynthetic or ((AudioInputProcessor.ValidateSettings=0) and (AudioInputProcessor.CheckPlayersConfig(N)=0)));
  end;
  if J.Find('routes').JSONType<>jtArray then Exit;
  Routes:=J.Arrays['routes'];
  if Routes.Count<>N then Exit;
  for I:=0 to N-1 do
  begin
    if Routes[I].JSONType<>jtObject then Exit;
    Entry:=Routes.Objects[I]; R[I].Mobile:=Entry.Get('mobile',false);
    R[I].DelayMs:=EnsureRange(Entry.Get('latency_ms',Ini.MicDelay),-500,500)-Ini.MicDelay;
    R[I].Gain:=EnsureRange(Entry.Get('gain',Gains[I]*1.0),0.0,1.0);
    if R[I].Mobile then begin HasMobile:=true; Continue; end;
    D:=Entry.Get('device',-1); C:=Entry.Get('channel',-1); R[I].Device:=D; R[I].Channel:=C;
    for K:=0 to I-1 do
      if not R[K].Mobile and (R[K].Device=D) and (R[K].Channel=C) then Exit;
    if ShellSynthetic then Continue;
    if (D<0) or (D>High(AudioInputProcessor.DeviceList)) then Exit;
    if (C<0) or (C>=AudioInputProcessor.DeviceList[D].AudioFormat.Channels) then Exit;
    if Entry.Get('name','')<>AudioInputProcessor.DeviceList[D].Name then Exit;
    for K:=0 to High(AudioInputProcessor.DeviceList) do
      if (K<>D) and (AudioInputProcessor.DeviceList[K].Name=AudioInputProcessor.DeviceList[D].Name) then Exit;
  end;
  if HasMobile then
  begin
    ActiveMobileSecret:=J.Get('mobile_secret','');
    if not MobileOpen(ActiveMobileSecret) then Exit;
  end;
  if not ShellSynthetic then
  begin
    SetLength(SavedChannels,Length(Ini.InputDeviceConfig));
    for D:=0 to High(SavedChannels) do
    begin
      SavedChannels[D]:=Copy(Ini.InputDeviceConfig[D].ChannelToPlayerMap);
      for C:=0 to High(SavedChannels[D]) do Ini.InputDeviceConfig[D].ChannelToPlayerMap[C]:=CHANNEL_OFF;
    end;
  end;
  for I:=0 to N-1 do
  begin
    MobileSlot[I]:=R[I].Mobile;
    if R[I].DelayMs<>0 then KaraokeHasRouteDelay:=true;
    AudioInputProcessor.Sound[I].MonitorGain:=R[I].Gain;
    AudioInputProcessor.Sound[I].RouteDelayMs:=R[I].DelayMs;
    if not R[I].Mobile and not ShellSynthetic then
    begin
      Config:=AudioInputProcessor.DeviceList[R[I].Device].CfgIndex;
      Ini.InputDeviceConfig[Config].ChannelToPlayerMap[R[I].Channel]:=I+1;
    end;
  end;
  Result:=true;
end;

procedure FeedMobile(Slot: integer; var Frame: TMobileFrame);
begin
  AudioInputProcessor.Sound[Slot].TestFeed(@Frame[0],SizeOf(Frame));
end;
procedure ShellCaptureStart;
var I: integer; Slots: Word; Fmt: TAudioFormatInfo;
begin
  if CaptureActive then Exit;
  CaptureCount:=PlayersPlay; CaptureActive:=true; Slots:=0;
  if not ShellSynthetic then AudioInput.CaptureStart;
  Fmt:=TAudioFormatInfo.Create(1,48000,asfS16);
  try
    for I:=0 to CaptureCount-1 do
      if ShellSynthetic or MobileSlot[I] then
      begin
        if MobileSlot[I] then Slots:=Slots or (1 shl I);
        SynthFeeding[I]:=not MobileSlot[I];
        AudioInputProcessor.Sound[I].TestStart(Fmt);
      end;
  finally Fmt.Free; end;
  if Slots<>0 then MobileArm(Slots,@FeedMobile);
  SynthTick:=SDL_GetTicks; SynthPosition:=0;
end;

procedure ShellCaptureStop;
var I: integer;
begin
  MobileClose; // Join the PCM callback before releasing any capture buffer.
  if CaptureActive then
  begin
    if not ShellSynthetic then AudioInput.CaptureStop;
    for I:=0 to CaptureCount-1 do
    begin
      if ShellSynthetic or MobileSlot[I] then AudioInputProcessor.Sound[I].TestStop;
      MobileSlot[I]:=false; SynthPattern[I]:=false;
      AudioInputProcessor.Sound[I].RouteDelayMs:=0;
      AudioInputProcessor.Sound[I].MonitorGain:=Gains[I];
    end;
  end;
  CaptureActive:=false; KaraokeHasRouteDelay:=false; ActiveMobileSecret:=''; RestoreRoutes;
end;

procedure RequestQuit;
begin
  if Quitting then Exit;
  Quitting:=true;
  // Cancel a queued screen change before the next draw can start a song.
  Display.NextScreen:=nil;
  Display.NextScreenWithCheck:=nil;
  Display.CheckOK:=true;

  if CalibrationActive then CalibrationCancel;
  if Assigned(AudioPlayback) then AudioPlayback.QuiescePlayback;
  ShellCaptureStop;
  // A closed session restores its interrupted turn. EndSong would save a result.
  if Assigned(AudioPlayback) then
  begin
    AudioPlayback.Stop;
    AudioPlayback.SetSyncSource(nil);
  end;
  if Assigned(LyricsState) then
  begin
    LyricsState.Stop;
    LyricsState.SetSyncSource(nil);
  end;
end;

function AllDevicesOpened(N: integer): boolean;
var D,C,P: integer;
begin
  Result:=true;
  if ShellSynthetic then Exit;
  for D:=0 to High(AudioInputProcessor.DeviceList) do
    with AudioInputProcessor.DeviceList[D] do
      if not Capturing then for C:=0 to High(Ini.InputDeviceConfig[CfgIndex].ChannelToPlayerMap) do
      begin
        P:=Ini.InputDeviceConfig[CfgIndex].ChannelToPlayerMap[C];
        if (P>=1) and (P<=N) then Exit(false);
      end;
end;

procedure RefreshOutputIdentity;
var RawName: PAnsiChar; Spec: TSDL_AudioSpec;
begin
  OutputName:=SystemOutputID(KaraokeOutputDevice); OutputChecked:=SDL_GetTicks;
  if OutputName<>'' then Exit;
  RawName:=nil;
  if SDL_GetDefaultAudioInfo(RawName,@Spec,0)=0 then
    if Assigned(RawName) then
    begin
      OutputName:=UTF8String(RawName); SDL_free(RawName);
      if SameText(OutputName,'System default') or SameText(OutputName,'Default output') or
         SameText(OutputName,'System audio output device') then OutputName:='';
    end;
end;

procedure BeginCalibration(J: TJSONObject);
var Routes: TJSONObject; Entries: TJSONArray; Entry: TJSONObject;
begin
  if Singing or Assigned(Display.NextScreen) then begin ErrorText:='Mide el retorno entre canciones.'; Exit; end;
  if TestingInput then begin ShellCaptureStop; TestingInput:=false; end;
  RefreshOutputIdentity;
  CalibrationInputName:=J.Get('name',''); CalibrationDevice:=J.Get('device',-1);
  CalibrationChannel:=J.Get('channel',-1); CalibrationOutputName:=OutputName;
  CalibrationOutputRate:=KaraokeOutputHz;
  CalibrationState:='failed';
  CalibrationMessage:='No se pudo abrir la entrada seleccionada.';
  CalibrationResult:=Default(TCalibrationResult);
  if KaraokeOutputHz<=0 then begin CalibrationMessage:='No hay salida de audio disponible.'; Exit; end;
  Routes:=TJSONObject.Create;
  try
    Entries:=TJSONArray.Create; Routes.Add('routes',Entries);
    Entry:=TJSONObject.Create; Entries.Add(Entry);
    Entry.Add('device',J.Get('device',-1)); Entry.Add('name',J.Get('name',''));
    Entry.Add('channel',J.Get('channel',-1)); Entry.Add('gain',0.0);
    if not InstallRoutes(Routes,1) then Exit;
  finally Routes.Free; end;
  PlayersPlay:=1; ShellCaptureStart;
  if not AllDevicesOpened(1) then begin ShellCaptureStop; Exit; end;
  CalibrationDirect:=AudioInputProcessor.Sound[0].DirectMonitor;
  if CalibrationDirect then CalibrationOutputRate:=Round(AudioInputProcessor.Sound[0].AudioFormat.SampleRate);
  CalibrationStart(CalibrationClockMs(SDL_GetPerformanceCounter,SDL_GetPerformanceFrequency),CalibrationOutputRate,CalibrationDirect);
  CalibrationStarted:=SDL_GetTicks; CalibrationState:='running'; CalibrationMessage:='Escuchando siete pulsos…';
end;

procedure FinishCalibration;
begin
  CalibrationResult:=CalibrationFinish;
  ShellCaptureStop; RefreshOutputIdentity;
  if OutputName<>CalibrationOutputName then
  begin
    CalibrationResult:=Default(TCalibrationResult); CalibrationState:='failed';
    CalibrationMessage:='Cambió la salida durante la medición. Repite los pulsos con la salida elegida.'; Exit;
  end;
  if CalibrationResult.Success then begin CalibrationState:='done'; CalibrationMessage:='Recorrido del altavoz al micrófono.'; end
  else begin
    CalibrationState:='failed';
    if (CalibrationResult.InputFrames=0) or (CalibrationResult.InputPeak<3) then
      CalibrationMessage:='El micrófono no recibió señal. Revisa la entrada y el permiso de micrófono.'
    else if CalibrationResult.PulsesSent<5 then CalibrationMessage:='La salida no reprodujo suficientes pulsos.'
    else CalibrationMessage:='No se distinguieron suficientes pulsos. Acerca el micrófono al altavoz y repite la medida.';
  end;
end;
procedure BeginSong(J: TJSONObject);
var I,K,N: integer; Names: TJSONArray; Found: boolean; FileName: string;
begin
  if Singing or Assigned(Display.NextScreen) then begin ErrorText:='Hay una interpretación en curso.'; Exit; end;
  if TestingInput then begin ShellCaptureStop; TestingInput:=false; end;
  RefreshOutputIdentity;
  if Assigned(J.Find('output_device')) and (J.Get('output_device','')<>OutputName) then
  begin ErrorText:='Cambió la salida de audio. Comprueba el ajuste del micrófono y vuelve a iniciar.'; Exit; end;
  FileName:=J.Get('chart','');
  if not FileExists(FileName) then begin ErrorText:='No se encuentra el mapa.'; Exit; end;
  if Songs.ShellImport(Path(FileName)) then CatSongs.Refresh;
  Found:=false;
  for I:=0 to High(CatSongs.Song) do
    if CatSongs.Song[I].Path.Append(CatSongs.Song[I].FileName).ToNative=FileName then
    begin
      Names:=J.Arrays['names']; N:=Names.Count;
      if (N<1) or (N>KaraokeMaxSingers) then begin ErrorText:='Elige de uno a diez cantantes.'; Exit; end;
      if not InstallRoutes(J,N) then
      begin ErrorText:='Asigna una entrada disponible y distinta a cada cantante.'; Exit; end;
      for K := 0 to High(PitchTraces) do PitchTraces[K].Active := false;
      // The legacy theme selector has five options and is not a singer count.
      if N<=2 then Ini.Players:=N-1 else Ini.Players:=0;
      PlayersPlay:=N;
      ShellCaptureStart;
      if not AllDevicesOpened(N) then
      begin ShellCaptureStop; ErrorText:='No se pudo abrir un micrófono. Comprueba la conexión y el permiso.'; Exit; end;
      SetLength(Player,N);
      for K:=0 to N-1 do
      begin
        Ini.Name[K]:=Names.Strings[K]; Player[K].Name:=Names.Strings[K]; Player[K].Level:=EnsureRange(J.Get('precision',1),0,2);
        AvatarPlayerTextures[K+1]:=NoAvatarTexture[K+1];
      end;
      if not Assigned(ScreenSing) then
      begin
        LoadPlayersColors; Theme.ThemeScoreLoad;
        ScreenScore.Free; ScreenScore:=TScreenScore.Create;
        ScreenSing:=TScreenSingController.Create;
      end;
      ScreenSing.CheckPlayerConfigOnNextSong:=false;
      ScreenSong.Mode:=smNormal; CatSongs.Selected:=I;
      Token:=J.Get('token',''); ErrorText:=''; ResultsDismissed:=false; StageFocused:=false;
      Display.FadeTo(@ScreenSing); Found:=true; Break;
    end;
  if not Found then ErrorText:='El motor no admite este mapa.';
end;
procedure Command(J: TJSONObject);
var Op: string; I,K,D,C,P: integer; SilentFrame: SmallInt; Probe: TJSONObject;
begin
  Op:=J.Get('op','');
  ErrorText:='';
  if Op='start' then
  begin
    StartFailureToken:=''; StartFailureAttempt:=''; StartFailureMessage:='';
    try
      if CalibrationActive then ErrorText:='La medición termina en unos segundos.' else BeginSong(J);
    except on E:Exception do ErrorText:=E.Message; end;
    if ErrorText<>'' then
    begin
      StartFailureToken:=J.Get('token',''); StartFailureAttempt:=J.Get('attempt',''); StartFailureMessage:=ErrorText;
    end;
    Exit;
  end;
  if CalibrationActive and ((Op='gain') or (Op='testinput') or (Op='scan') or (Op='device') or (Op='calibrate')) then
  begin ErrorText:='La medición termina en unos segundos.'; Exit; end;
  if Op='calibrate' then BeginCalibration(J)
  else if (Op='test-pattern') and ShellSynthetic and Singing then
  begin
    I:=J.Get('player',-1);
    if (I>=0) and (I<CaptureCount) and not MobileSlot[I] then
    begin
      SynthPattern[I]:=true; SynthDelayMs[I]:=EnsureRange(J.Get('delay_ms',0),-500,500);
    end;
  end
  else if (Op='test-tone') and ShellSynthetic then
  begin
    I := J.Get('player',0);
    if (I >= 0) and (I <= High(SynthFrequency)) then
    begin
      SynthPattern[I]:=false;
      SynthFeeding[I] := J.Get('connected',true);
      SynthFrequency[I] := EnsureRange(J.Get('hz',0.0),0.0,2000.0);
      ProbePending[I]:=J.Get('measure',false) and (SynthFrequency[I]>0);
      if ProbePending[I] then
      begin
        ProbeClass[I]:=Round(69+12*Log2(SynthFrequency[I]/440.0)) mod 12; ProbeStart[I]:=SDL_GetTicks;
        ProbeMatched[I]:=false; ProbeFirstMs[I]:=-1; ProbeConfirmMs[I]:=-1;
      end;
    end;
  end
  else if (Op='test-silent-frame') and ShellSynthetic and Singing then
  begin
    I:=J.Get('player',-1);
    if (I<0) or (I>=PlayersPlay) then Exit;
    // Query immediately after one frame so later callbacks cannot hide stale samples.
    SilentFrame:=0;
    AudioInputProcessor.Sound[I].TestFeed(@SilentFrame,SizeOf(SilentFrame));
    Probe:=TJSONObject.Create;
    try
      Probe.Add('pitch',AudioInputProcessor.Sound[I].DetectedPitch);
      SaveJSON(Root+'/test-silent-frame.json',Probe);
    finally Probe.Free; end;
  end
  else if (Op='test-screenshot') and ShellSynthetic then CaptureTestFrame := true
  else if Op='panel' then SetPanelCollapsed(J.Get('collapsed',not PanelCollapsed))
  else if Op='gain' then
  begin
    I:=J.Get('player',0);
    if (I<0) or (I>=KaraokeMaxSingers) then Exit;
    Gains[I]:=EnsureRange(J.Get('value',0.0),0.0,1.0);
    AudioInputProcessor.Sound[I].MonitorGain:=Gains[I];
  end
  else if Op='forget' then PendingForget.Add(J.Get('chart',''))
  else if Op='music' then SetAudioVolumePercent(J.Get('value',65))
  else if Op='latency' then begin if not Singing then Ini.MicDelay:=EnsureRange(J.Get('value',0),-500,500); end
  else if Op='pause' then begin if Singing then ScreenSing.Pause; end
  else if Op='set-paused' then
  begin
    if Singing and (Token=J.Get('token','')) and (ScreenSing.Paused<>J.Get('paused',false)) then
      ScreenSing.Pause;
  end
  else if Op='end' then
  begin
    if Singing and (Token=J.Get('token',Token)) then ScreenSing.EndSong;
  end
  else if Op='testinput' then
  begin
    if Singing then begin ErrorText:='Prueba los micrófonos entre canciones.'; Exit; end;
    if TestingInput then begin ShellCaptureStop; TestingInput:=false; end
    else begin PlayersPlay:=EnsureRange(J.Get('count',2),1,KaraokeMaxSingers); ShellCaptureStart; TestingInput:=true; end;
  end
  else if Op='scan' then
  begin
    if Singing then ErrorText:='Espera a terminar para detectar entradas.'
    else begin if TestingInput then begin ShellCaptureStop; TestingInput:=false; end; RefreshAudioInputDevices(aimFull); ErrorText:=''; end;
  end
  else if Op='device' then
  begin
    if Singing then begin ErrorText:='Cambia el micrófono entre canciones.'; Exit; end;
    if TestingInput then begin ShellCaptureStop; TestingInput:=false; end;
    D:=J.Get('device',-1); C:=J.Get('channel',-1); P:=J.Get('player',0)+1;
    if (D<0) or (D>High(AudioInputProcessor.DeviceList)) or (P<1) or (P>KaraokeMaxSingers) then Exit;
    K:=AudioInputProcessor.DeviceList[D].CfgIndex;
    if (C<0) or (C>High(Ini.InputDeviceConfig[K].ChannelToPlayerMap)) then Exit;
    for D:=0 to High(Ini.InputDeviceConfig) do
      for I:=0 to High(Ini.InputDeviceConfig[D].ChannelToPlayerMap) do
        if Ini.InputDeviceConfig[D].ChannelToPlayerMap[I]=P then Ini.InputDeviceConfig[D].ChannelToPlayerMap[I]:=CHANNEL_OFF;
    Ini.InputDeviceConfig[K].ChannelToPlayerMap[C]:=P;
    Ini.Save; ErrorText:='';
  end
  else if Op='quit' then RequestQuit;
end;
procedure EditChanged;
begin
  LastEditTick:=SDL_GetTicks;
  Composition:='';
end;

procedure PublishSearch;
begin
  if (EditAction='field:query') and (EditValue<>LastSubmitted) then
  begin
    Emit(EditAction,EditValue);
    LastSubmitted:=EditValue;
  end;
end;

procedure ShellTick;
var J,O: TJSONObject; A,Scores,Devices,Levels: TJSONArray; SR: TSearchRec;
    Commands: TStringList; Forgotten: TSong;
    I,K,N: integer; NowTick: cardinal; Buf: array[0..4095] of SmallInt;
    Frequency,SampleTime,SongTime: double; Name,FocusKey: string; NewFocus: integer; EnterSearch: boolean;
begin
  if Quitting or not ShellEnabled then Exit;
  NowTick:=SDL_GetTicks;
  if not Started then
  begin
    // The standalone Deluxe main menu owns this modal. In the embedded shell
    // it would cover the singers' notes and cannot receive the shell's input.
    WantSoftwareRenderingMsg:=false;
    Started:=true; PendingForget:=TStringList.Create; Ini.ScreenFade:=0; Ini.VoicePassthrough:=1; Ini.MicBoost:=0;
    Ini.BackgroundMusicOption:=0; Ini.PreviewVolume:=0; Ini.SavePlayback:=0; Ini.AskbeforeDel:=0;
    Ini.Mouse:=1; Display.SetCursor;
    SDL_SetWindowTitle(screen,'Karaoke'); SDL_SetWindowMinimumSize(screen,1000,640);
    for I:=0 to KaraokeMaxSingers-1 do
    begin
      SynthFrequency[I]:=440; AudioInputProcessor.Sound[I].MonitorGain:=0;
    end;
    SynthFrequency[1]:=493.883;
  end;
  Commands:=TStringList.Create;
  try
    if FindFirst(Root+'/commands/*.json',faAnyFile,SR)=0 then
    begin
      repeat Commands.Add(SR.Name); until FindNext(SR)<>0;
      FindClose(SR);
    end;
    Commands.Sort;
    for I:=0 to Commands.Count-1 do
    begin
      Name:=Root+'/commands/'+Commands[I]; J:=nil;
      try J:=ReadJSON(Name); DeleteFile(Name); Command(J);
      except on E: Exception do ErrorText:=E.Message; end;
      J.Free;
      if Quitting then Exit;
    end;
  finally Commands.Free; end;
  // Only refresh engine indexes at a safe point, never during a song.
  if not Singing and not Assigned(Display.NextScreen) then
    while PendingForget.Count>0 do
    begin
      for I:=Songs.SongList.Count-1 downto 0 do
      begin
        Forgotten:=TSong(Songs.SongList[I]);
        if Forgotten.Path.Append(Forgotten.FileName).ToNative=PendingForget[0] then
        begin
          if CurrentSong=Forgotten then CurrentSong:=nil;
          Songs.SongList.Delete(I); CatSongs.Refresh; Forgotten.Free;
        end;
      end;
      PendingForget.Delete(0);
    end;
  // Query the system between performances; some SDL drivers contact the sound server.
  if not Singing and not CalibrationActive and ((OutputChecked=0) or (NowTick-OutputChecked>5000)) then RefreshOutputIdentity;
  if CalibrationActive and (NowTick-CalibrationStarted>=CalibrationDurationMs) then FinishCalibration;
  if MobilePort<>0 then MobileSetPaused(not Singing or ScreenSing.Paused);
  if ShellSynthetic and (Singing or TestingInput) and not Assigned(Display.NextScreen) then
  begin
    N:=Min(4096,Round((NowTick-SynthTick)*48));
    if N>0 then
    begin
      SongTime:=AudioPlayback.Position;
      for I:=0 to PlayersPlay-1 do
      begin
        if not SynthFeeding[I] then Continue;
        Frequency := SynthFrequency[I];
        for K:=0 to N-1 do
        begin
          if SynthPattern[I] then
          begin
            // Deterministic alternating A4/C5 test fixture, delayed at the input.
            SampleTime:=SongTime-(N-K)/48000-SynthDelayMs[I]/1000.0;
            if Odd(Floor((SampleTime-1.0)*4)) then Frequency:=523.251 else Frequency:=440;
          end;
          Buf[K]:=Round(8000*Sin(2*Pi*Frequency*(SynthPosition+K)/48000));
        end;
        AudioInputProcessor.Sound[I].TestFeed(@Buf[0],N*2);
      end;
      Inc(SynthPosition,N); SynthTick:=NowTick;
    end;
  end;
  if (not PanelCollapsed) and (Composition='') and (NowTick-LastEditTick>=350) then PublishSearch;
  if NowTick-LastView>150 then
  begin
    LastView:=NowTick;
    if FileExists(Root+'/view.json') then
    try
      FocusKey:=FocusAction;
      J:=ReadJSON(Root+'/view.json');
      EnterSearch:=(J.Get('page','')='Buscar') and (Page<>'Buscar');
      if J.Get('page','')<>Page then
      begin
        Page:=J.Get('page',''); HeldAdd:=''; HoverAdd:=''; ConfirmedAdd:='';
        // Tabs keep their focus on navigation. Page-local controls do not.
        if (Focus< -10) or (Focus> -7) then begin Focus:=-1; StageFocused:=false; FocusKey:=''; end;
        EditAction:=''; EditValue:=''; Composition:=''; EditSelectedAll:=false; Scroll:=0; SDL_StopTextInput;
      end;
      View.Free; View:=J;
      if (PendingAddToken<>'') and (View.Get('added_token','')=PendingAddToken) then
      begin
        ConfirmedAdd:=PendingAdd; ConfirmedAt:=NowTick; PendingAddToken:='';
      end;
      if EnterSearch and not PanelCollapsed then
        for I:=0 to View.Arrays['rows'].Count-1 do
        begin
          O:=TJSONObject(View.Arrays['rows'][I]);
          if O.Get('action','')='field:query' then
          begin
            Focus:=I; StageFocused:=false; AddFocused:=false; FocusKey:='field:query';
            EditAction:=FocusKey; EditValue:=O.Get('value',''); LastSubmitted:=EditValue;
            SDL_StartTextInput; Break;
          end;
        end;
      // Async rows may be inserted or removed. Preserve the action, never its old index.
      if Focus>=0 then
      begin
        NewFocus:=-1;
        if FocusKey<>'' then for I:=0 to View.Arrays['rows'].Count-1 do
          begin
            O:=TJSONObject(View.Arrays['rows'][I]);
            if (O.Get('action','')=FocusKey) or (O.Get('add_action','')=FocusKey) then
            begin NewFocus:=I; AddFocused:=O.Get('add_action','')=FocusKey; Break; end;
          end;
        Focus:=NewFocus;
      end;
      if (FocusAction='') or ((EditAction<>'') and (FocusAction<>EditAction)) then
      begin Focus:=-1; EditAction:=''; EditValue:=''; EditSelectedAll:=false; SDL_StopTextInput; end;
    except end;
  end;
  if NowTick-LastStatus>200 then
  begin
    LastStatus:=NowTick; J:=TJSONObject.Create;
    if TestingInput then for I:=0 to CaptureCount-1 do AudioInputProcessor.Sound[I].AnalyzeBuffer;
    try
      if Singing then J.Add('state','singing') else J.Add('state','idle');
      J.Add('paused', Singing and ScreenSing.Paused);
      J.Add('cursor_visible',SDL_ShowCursor(SDL_QUERY)=SDL_ENABLE);
      J.Add('mouse_x',LastMouseX); J.Add('mouse_y',LastMouseY); J.Add('mouse_clicks',MouseClicks); J.Add('width',ScreenW); J.Add('height',ScreenH); J.Add('last_action',LastAction);
      J.Add('drawable_width',DrawableW); J.Add('drawable_height',DrawableH);
      J.Add('pixel_scale_x',DrawableScaleX); J.Add('pixel_scale_y',DrawableScaleY);
      J.Add('panel_collapsed',PanelCollapsed); J.Add('panel_width',SideWidth);
      J.Add('stage_width',ScreenW-SideWidth);
      if PanelCollapsed then
      begin
        if PanelToggleFocused then J.Add('focus_action','panel') else J.Add('focus_action','');
      end else J.Add('focus_action',FocusAction);
      J.Add('edit_selected',EditSelectedAll);
      if ShellSynthetic then
      begin
        A:=TJSONArray.Create; for I:=0 to Max(2,CaptureCount)-1 do A.Add(ProbeFirstMs[I]); J.Add('trace_first_ms',A);
        A:=TJSONArray.Create; for I:=0 to Max(2,CaptureCount)-1 do A.Add(ProbeConfirmMs[I]); J.Add('trace_confirm_ms',A);
      end;
      J.Add('testing',TestingInput); J.Add('synthetic',ShellSynthetic);
      J.Add('token',Token); J.Add('error',ErrorText);
      O:=TJSONObject.Create; O.Add('token',StartFailureToken); O.Add('attempt',StartFailureAttempt); O.Add('message',StartFailureMessage); J.Add('start_failure',O);
      if Assigned(CurrentSong) then J.Add('title',CurrentSong.Title) else J.Add('title','');
      J.Add('position',AudioPlayback.Position);
      Scores:=TJSONArray.Create; Levels:=TJSONArray.Create;
      for I:=0 to High(Player) do
      begin
        Scores.Add(Player[I].ScoreTotalInt);
      end;
      N:=Max(2,CaptureCount);
      for I:=0 to N-1 do Levels.Add(AudioInputProcessor.Sound[I].MaxSampleVolume);
      J.Add('scores',Scores); J.Add('levels',Levels);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].Tone); J.Add('tones',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].MonitorPeak); J.Add('monitor_peaks',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].CaptureAgeMs); J.Add('input_age_ms',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].BlockFrames); J.Add('input_frames',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].MonitorQueueMs); J.Add('monitor_queue_ms',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].MonitorDroppedFrames); J.Add('monitor_dropped_frames',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(AudioInputProcessor.Sound[I].DirectMonitor); J.Add('duplex_monitor',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(MobileReceived(I)); J.Add('mobile_received',A);
      A:=TJSONArray.Create; for I:=0 to N-1 do A.Add(MobileMissing(I)); J.Add('mobile_gap_frames',A);
      J.Add('mobile_rejected',MobileRejected); J.Add('mobile_discarded',MobileDiscarded);
      J.Add('max_singers',KaraokeMaxSingers); J.Add('mobile_port',MobilePort);
      J.Add('output_frames',KaraokeOutputFrames); J.Add('output_hz',KaraokeOutputHz);
      O:=TJSONObject.Create; J.Add('calibration',O);
      O.Add('name',CalibrationInputName); O.Add('device',CalibrationDevice); O.Add('channel',CalibrationChannel);
      if CalibrationDirect then O.Add('monitor_path','duplex') else O.Add('monitor_path','mixer');
      O.Add('output_device',CalibrationOutputName); O.Add('output_hz',CalibrationOutputRate);
      J.Add('output_device',OutputName);
      O.Add('status',CalibrationState); O.Add('message',CalibrationMessage);
      O.Add('roundtrip_ms',CalibrationResult.RoundtripMs); O.Add('spread_ms',CalibrationResult.SpreadMs);
      O.Add('samples',CalibrationResult.Samples); O.Add('input_frames',CalibrationResult.InputFrames);
      O.Add('input_peak',CalibrationResult.InputPeak); O.Add('pulses_sent',CalibrationResult.PulsesSent);
      J.Add('audio_driver',KaraokeOutputDevice); J.Add('capture_backend',AudioInput.GetName);
      Devices:=TJSONArray.Create;
      for I:=0 to High(AudioInputProcessor.DeviceList) do
      begin
        O:=TJSONObject.Create;
        O.Add('index',I); O.Add('name',AudioInputProcessor.DeviceList[I].Name);
        with AudioInputProcessor.DeviceList[I] do
          if HasAdcTime and Capturing then O.Add('adc_to_callback_ms',AdcToCallbackMs);
        with AudioInputProcessor.DeviceList[I] do
          if HasDacTime and Capturing then O.Add('callback_to_dac_ms',CallbackToDacMs);
        O.Add('output_underflows',AudioInputProcessor.DeviceList[I].OutputUnderflows);
        O.Add('input_overflows',AudioInputProcessor.DeviceList[I].Overflows);
        O.Add('channels',AudioInputProcessor.DeviceList[I].AudioFormat.Channels);
        O.Add('hz',AudioInputProcessor.DeviceList[I].AudioFormat.SampleRate);
        A:=TJSONArray.Create;
        K:=AudioInputProcessor.DeviceList[I].CfgIndex;
        for N:=0 to High(Ini.InputDeviceConfig[K].ChannelToPlayerMap) do A.Add(Ini.InputDeviceConfig[K].ChannelToPlayerMap[N]);
        O.Add('players',A); Devices.Add(O);
      end;
      J.Add('devices',Devices); SaveJSON(Root+'/engine.json',J);
    finally J.Free; end;
  end;
end;
procedure ShellViewport;
var W,H,X,Y: integer;
begin
  W:=Min(ScreenW-SideWidth,Round(ScreenH*4/3)); H:=Min(ScreenH,Round(W*0.75));
  X:=(ScreenW-SideWidth-W) div 2; Y:=(ScreenH-H) div 2;
  Renderer.SetViewPort(X,Y,W,H);
end;
procedure TrimLast(var S: UTF8String);
var I: integer;
begin
  I:=Length(S); if I=0 then Exit;
  while (I>1) and ((Ord(S[I]) and $C0)=$80) do Dec(I);
  Delete(S,I,Length(S)-I+1);
end;
procedure LabelAt(X,Y,Size: single; const S: UTF8String; Width: single=360; Muted: boolean=false; Strong: boolean=false; OnAccent: boolean=false);
var T: UTF8String;
begin
  SetFontFamily(0); if Strong then SetFontStyle(ftBold) else SetFontStyle(ftRegular); ResetFont; SetFontSize(Size);
  if OnAccent then SetFontColor(InkOnAccent.R,InkOnAccent.G,InkOnAccent.B,1)
  else if Muted then SetFontColor(InkMuted.R,InkMuted.G,InkMuted.B,1)
  else SetFontColor(InkText.R,InkText.G,InkText.B,1);
  T:=S;
  if TextWidth(T)>Width then
  begin
    while (Length(T)>0) and (TextWidth(T+'...')>Width) do TrimLast(T);
    T:=T+'...';
  end;
  SetFontPos(X,Y); PrintText(T); Renderer.DepthTest:=false;
end;

procedure ShellGroupLabel(X,Y,W,Singer: integer);
begin
  Renderer.DrawQuad(X,Y,0,W,24,0.06,0.14,0.13,0.92);
  LabelAt(X+6,Y+3,16,Player[Singer].Name,W-88,false,true);
  LabelAt(X+W-77,Y+3,16,IntToStr(Player[Singer].ScoreTotalInt),72,false,true);
end;

procedure Rect(X,Y,W,H: single; R,G,B: single); overload;
begin Renderer.DrawQuad(X,Y,0,W,H,R,G,B,1); end;
procedure Rect(X,Y,W,H: single; const Color: TSessionColor); overload;
begin Rect(X,Y,W,H,Color.R,Color.G,Color.B); end;
function StageSong: TJSONObject;
begin
  Result:=nil;
  if Assigned(View) and (View.Find('stage') is TJSONObject) then Result:=View.Objects['stage'];
end;
function ShowingResults: boolean;
begin Result:=(Token<>'') and not ResultsDismissed; end;
type
  TBox = record X,Y,W,H: single; end;
function Box(X,Y,W,H: single): TBox;
begin Result.X:=X; Result.Y:=Y; Result.W:=W; Result.H:=H; end;
function Inside(const B: TBox; X,Y: single): boolean;
begin Result:=(X>=B.X) and (Y>=B.Y) and (X<B.X+B.W) and (Y<B.Y+B.H); end;
procedure Fill(const B: TBox; R,G,Blue: single);
begin Rect(B.X,B.Y,B.W,B.H,R,G,Blue); end;
procedure Outline(const B: TBox; R,G,Blue: single);
begin
  Rect(B.X-2,B.Y-2,B.W+4,2,R,G,Blue); Rect(B.X-2,B.Y+B.H,B.W+4,2,R,G,Blue);
  Rect(B.X-2,B.Y,2,B.H,R,G,Blue); Rect(B.X+B.W,B.Y,2,B.H,R,G,Blue);
end;
// Rounded surfaces are one triangle batch, independent of the drawable scale.
procedure Surface(const B: TBox; Radius,R,G,Blue: single); overload;
const Steps=6;
var Mesh: TTriangleList; I,Corner,Step: integer; Angle,CX,CY,X,Y,PX,PY: single;
begin
  Radius:=Min(Radius,Min(B.W,B.H)/2);
  SetLength(Mesh,4*(Steps+1)); I:=0; PX:=B.X+B.W-Radius; PY:=B.Y;
  for Corner:=0 to 3 do
  begin
    if Corner in [0,1] then CX:=B.X+B.W-Radius else CX:=B.X+Radius;
    if Corner in [0,3] then CY:=B.Y+Radius else CY:=B.Y+B.H-Radius;
    for Step:=0 to Steps do
    begin
      Angle:=((Corner-1)+Step/Steps)*Pi/2;
      X:=CX+Radius*Cos(Angle); Y:=CY+Radius*Sin(Angle);
      Mesh[I].X1:=B.X+B.W/2; Mesh[I].Y1:=B.Y+B.H/2;
      Mesh[I].X2:=PX; Mesh[I].Y2:=PY; Mesh[I].X3:=X; Mesh[I].Y3:=Y;
      Mesh[I].ColR:=R; Mesh[I].ColG:=G; Mesh[I].ColB:=Blue; Mesh[I].Alpha:=1;
      PX:=X; PY:=Y; Inc(I);
    end;
  end;
  // The first triangle closes the final straight edge of the perimeter.
  Mesh[0].X2:=PX; Mesh[0].Y2:=PY;
  Renderer.DrawTriangles(Mesh);
end;

procedure Surface(const B: TBox; Radius: single; const Color: TSessionColor); overload;
begin Surface(B,Radius,Color.R,Color.G,Color.B); end;

procedure FocusInset(const B:TBox);
begin
  Surface(Box(B.X-1,B.Y-1,B.W+2,B.H+2),7,InkFocus);
end;

procedure Chevron(X,Y: single; Right: boolean; Size: single=4);
var DX: single;
begin
  DX:=Size; if not Right then DX:=-Size;
  Renderer.DrawLine(X-DX/2,Y-Size,X+DX/2,Y,0,1.5,InkMuted.R,InkMuted.G,InkMuted.B,1);
  Renderer.DrawLine(X+DX/2,Y,X-DX/2,Y+Size,0,1.5,InkMuted.R,InkMuted.G,InkMuted.B,1);
end;

function CachedCover(const FileName: string): TTexture;
var I,Slot: integer;
begin
  Result:=nil; if FileName='' then Exit;
  Inc(CoverUse); Slot:=0;
  for I:=Low(CoverPaths) to High(CoverPaths) do
  begin
    if CoverPaths[I]=FileName then
    begin CoverTimes[I]:=CoverUse; Exit(CoverTextures[I]); end;
    if CoverTimes[I]<CoverTimes[Slot] then Slot:=I;
  end;
  FreeAndNil(CoverTextures[Slot]); CoverPaths[Slot]:=FileName; CoverTimes[Slot]:=CoverUse;
  try CoverTextures[Slot]:=Renderer.LoadTexture(Path(FileName)); except CoverTextures[Slot]:=nil; end;
  Result:=CoverTextures[Slot];
end;
function Initials(const Name: UTF8String): UTF8String;
var Words: UnicodeString; I: integer;
begin
  Words:=Trim(UTF8Decode(Name)); if Words='' then Exit('');
  // Keep complete non-BMP glyphs in case an artist name starts with one.
  I:=Length(Words); while (I>1) and (Words[I-1]<>' ') do Dec(I);
  if (Ord(Words[1]) >= $D800) and (Ord(Words[1]) <= $DBFF) then Result:=UTF8Encode(Copy(Words,1,2))
  else Result:=UTF8Encode(UnicodeUpperCase(Copy(Words,1,1)));
  if I>1 then
    if (Ord(Words[I]) >= $D800) and (Ord(Words[I]) <= $DBFF) then Result:=Result+UTF8Encode(Copy(Words,I,2))
    else Result:=Result+UTF8Encode(UnicodeUpperCase(Copy(Words,I,1)));
end;
procedure Artwork(Song: TJSONObject; const B: TBox);
var T: TTexture; Name,Letters: UTF8String; I,Swatch: integer; TextSize: single;
begin
  T:=CachedCover(Song.Get('cover',''));
  if Assigned(T) then
  begin
    T.X:=B.X; T.Y:=B.Y; T.W:=B.W; T.H:=B.H; T.Z:=0;
    T.ColR:=1; T.ColG:=1; T.ColB:=1; T.Alpha:=1; T.Reflection:=false;
    Renderer.DrawTexture(T); Exit;
  end;
  Name:=Song.Get('artist',''); if Name='' then Name:=Song.Get('title',Song.Get('label',''));
  Swatch:=0; for I:=1 to Length(Name) do Swatch:=(Swatch*31+Ord(Name[I])) mod 641;
  case Swatch mod 6 of
    0: Fill(B,0.36,0.18,0.28); 1: Fill(B,0.19,0.30,0.36);
    2: Fill(B,0.22,0.32,0.24); 3: Fill(B,0.35,0.24,0.18);
    4: Fill(B,0.26,0.22,0.37); 5: Fill(B,0.36,0.19,0.22);
  end;
  Letters:=Initials(Name); TextSize:=B.W*0.35;
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(TextSize);
  LabelAt(B.X+(B.W-TextWidth(Letters))/2,B.Y+B.H*0.36,TextSize,Letters,B.W);
end;
function HeroArt(W: single): TBox;
var S: single;
begin
  S:=Min(460,Min(W*0.46,ScreenH*0.51));
  Result:=Box(40,Max(82,(ScreenH-108-S)/2),S,S);
end;
function HeroButton(W: single): TBox;
var Art: TBox;
begin Art:=HeroArt(W); Result:=Box(Art.X+Art.W+28,Art.Y+Art.H*0.67,Min(178,W-Art.X-Art.W-60),44); end;
function EmptyButton: TBox;
begin Result:=Box(40,ScreenH*0.50+94,218,46); end;
function ResultButton: TBox;
begin Result:=Box(40,ScreenH-110,218,46); end;
procedure DrawAddCheck(X,Y:single);
begin
  Renderer.DrawLine(X-7,Y,X-2,Y+5,0,2.2,InkSignal.R,InkSignal.G,InkSignal.B,1);
  Renderer.DrawLine(X-2,Y+5,X+7,Y-5,0,2.2,InkSignal.R,InkSignal.G,InkSignal.B,1);
end;
procedure PrimaryButton(const B: TBox; const Caption: UTF8String; Focused: boolean);
begin
  if Focused then FocusInset(B);
  Surface(B,7,InkAccent);
  LabelAt(B.X+17,B.Y+13,16,Caption,B.W-32,false,true,true);
end;
procedure TitleAt(X,Y,Size,W: single; const Title: UTF8String);
var Line,Rest: UTF8String; I,Cut: integer;
begin
  SetFontFamily(0); SetFontStyle(ftBold); ResetFont; SetFontSize(Size);
  if TextWidth(Title)<=W then begin LabelAt(X,Y,Size,Title,W,false,true); Exit; end;
  Rest:=Title; Line:=''; Cut:=0;
  for I:=1 to Length(Title) do if Title[I]=' ' then
  begin
    if TextWidth(Copy(Title,1,I-1))>W then Break;
    Cut:=I;
  end;
  if Cut=0 then begin LabelAt(X,Y,Size,Title,W,false,true); Exit; end;
  Line:=Copy(Title,1,Cut-1); Delete(Rest,1,Cut);
  LabelAt(X,Y,Size,Line,W,false,true); LabelAt(X,Y+Size*1.20,Size,Rest,W,false,true);
end;
procedure PitchPreview(X,Y:single);
const Tones:array[0..5] of integer=(1,2,2,3,1,0);
      Lengths:array[0..5] of integer=(30,49,24,42,37,63);
var I:integer; P:single;
begin
  for I:=0 to 3 do Rect(X,Y+I*14,291,1,0.18,0.19,0.23);
  P:=X;
  for I:=0 to 5 do
  begin
    if I<3 then Surface(Box(P,Y+Tones[I]*14-3,Lengths[I],7),3,InkAccent)
    else Surface(Box(P,Y+Tones[I]*14-3,Lengths[I],7),3,InkGuide);
    P:=P+Lengths[I]+9;
  end;
end;
procedure DrawStage(W: integer);
var Song: TJSONObject; I,Players,Cols,RowCount: integer;
    Art,B: TBox; X,CellW,CellH,TextW,TitleSize,Y: single; Caption: string;
begin
  Rect(0,0,W,ScreenH,InkStage);
  if ShowingResults then
  begin
    LabelAt(40,36,18,'Puntuación',W-80,true);
    if Assigned(CurrentSong) then begin
      TitleAt(40,79,Min(42,W/16),W-80,CurrentSong.Title);
      LabelAt(40,186,21,CurrentSong.Artist,W-80,true);
    end;
    Players:=Min(10,Length(Player)); Cols:=1;
    if Players>5 then Cols:=2;
    RowCount:=Max(1,(Players+Cols-1) div Cols);
    CellH:=Min(85.0,(ResultButton.Y-265)/RowCount);
    CellW:=(W-80)/Cols;
    for I:=0 to Players-1 do
    begin
      X:=40+(I div RowCount)*CellW; Y:=216+(I mod RowCount)*CellH;
      Rect(X,Y,CellW-12,1,InkLine);
      LabelAt(X+3,Y+8,Min(22,CellH*0.39),Player[I].Name,CellW-91,false,true);
      LabelAt(X+CellW-84,Y+8,Min(23,CellH*0.40),IntToStr(Player[I].ScoreTotalInt),76,false,true);
    end;
    if Assigned(View) then LabelAt(40,ResultButton.Y-36,16,View.Get('next',''),W-80,true);
    PrimaryButton(ResultButton,'Volver a la sesión',StageFocused);
  end else if Assigned(StageSong) then
  begin
    Song:=StageSong;
    LabelAt(40,32,18,'Próximo turno',W-80,true);
    Art:=HeroArt(W); Artwork(Song,Art);
    B:=HeroButton(W); X:=B.X; TextW:=W-X-34; TitleSize:=Min(44,TextW/6.3);
    LabelAt(X,Art.Y+Art.H*0.12,Min(19,TextW/10),Song.Get('artist',''),TextW,true);
    TitleAt(X,Art.Y+Art.H*0.25,TitleSize,TextW,Song.Get('title',''));
    LabelAt(X,Art.Y+Art.H*0.54,17,Song.Get('names',''),TextW,true);
    if Pos('start:',Song.Get('action',''))=1 then Caption:='Empezar a cantar' else Caption:='Ver preparación';
    PrimaryButton(B,Caption,StageFocused and KeyboardFocusVisible);
  end else
  begin
    Y:=ScreenH*0.5;
    PitchPreview(40,Y-102);
    TitleAt(40,Y-18,36,W-80,'Tu primera canción');
    if (Page='Buscar') and not PanelCollapsed then
      LabelAt(40,Y+44,19,'Añade una canción a la cola para empezar.',W-80,true)
    else PrimaryButton(EmptyButton,'Buscar canciones',StageFocused);
  end;
  if ShellSynthetic then LabelAt(40,ScreenH-22,12,'PRUEBA · Audio sintético, sin micrófono real',W-80,true);
end;
function SearchField(R: TJSONObject): boolean;
begin Result:=R.Get('action','')='field:query'; end;
function RowHeight(Row: TJSONObject): integer;
var Kind: string;
begin
  Kind:=Row.Get('kind','');
  if Kind='qr' then Result:=222
  else if Kind='song' then Result:=62
  else if SearchField(Row) then Result:=58
  else if Kind='input' then Result:=70
  else if Kind='slider' then Result:=60
  else if Row.Get('sub','')<>'' then Result:=64
  else if Row.Get('style','')='back' then Result:=38
  else Result:=44;
end;

function TabPage(I: integer): UTF8String;
begin
  case I of 1:Result:='Buscar'; 2:Result:='Cola'; else Result:='Ajustes'; end;
end;

function MainPage: boolean;
begin Result:=(Page='Buscar') or (Page='Cola') or (Page='Ajustes'); end;

function CurrentTab: integer;
begin
  if MainPage then begin
    for Result:=1 to 3 do if TabPage(Result)=Page then Exit;
  end;
  if (Page='Turno') or (Page='Preparaciones') or (Page='Terminar canción') then Result:=2
  else if (Page='Ediciones') or (Page='Versión') or (Page='Canción') or (Page='Opciones de canción') then Result:=1
  else Result:=3;
end;

function TabBox(I:integer):TBox;
const Left:array[1..3] of integer=(16,98,255);
      Widths:array[1..3] of integer=(70,80,78);
begin Result:=Box(Left[I],10,Widths[I],44); end;
function UndoBox:TBox;
begin Result:=Box(174,10,80,44); end;
function FoldBox:TBox;
begin Result:=Box(346,13,42,38); end;
function RestoreBox:TBox;
begin Result:=Box(ScreenW-164,16,148,40); end;
function TransportBox(Second:boolean):TBox;
begin Result:=Box(16+Ord(Second)*186,66,178,36); end;

function ContentTop: integer;
begin
  Result:=76;
  if Singing then Inc(Result,52);
  if not MainPage then Inc(Result,43);
end;

function StatusText: UTF8String;
begin
  Result:=ErrorText;
  if (Result='') and Assigned(View) then Result:=View.Get('message','');
end;
function FooterHeight: integer;
var Msg:UTF8String; Lines:integer;
begin
  Msg:=StatusText;
  if Msg='' then Exit(12);
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(14);
  Lines:=EnsureRange(Ceil(TextWidth(Msg)/336),1,3);
  Result:=24+Lines*19;
end;
function ContentBottom: integer;
begin Result:=Round(Height)-FooterHeight-5; end;
function AddBox(Y: single): TBox;
begin Result:=Box(337,Y+8,44,44); end;
function EditorTail(const Value: UTF8String; MaxWidth: single): UTF8String;
var L,R,M,Start: integer;
begin
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(18);
  if TextWidth(Value)<=MaxWidth then Exit(Value);
  L:=1; R:=Length(Value)+1;
  while L<R do
  begin
    M:=(L+R) div 2; Start:=M;
    while (Start<=Length(Value)) and ((Ord(Value[Start]) and $C0)=$80) do Inc(Start);
    if TextWidth(Copy(Value,Start,Length(Value)))<=MaxWidth then R:=M else L:=M+1;
  end;
  while (L<=Length(Value)) and ((Ord(Value[L]) and $C0)=$80) do Inc(L);
  Result:=Copy(Value,L,Length(Value));
end;
procedure SongRow(R: TJSONObject; Y: single; Focused,Hovered: boolean);
var B:TBox; TextW:single; Control:string;
begin
  Control:=RowAddKey(R.Get('add_action',''));
  B:=Box(16,Y,368,56);
  if Focused and not AddFocused then FocusInset(B);
  if (Focused and not AddFocused) or (Hovered and (HoverAdd<>Control)) then Surface(B,6,InkRaised)
  else Rect(82,Y+58,296,1,InkRaised);
  Artwork(R,Box(22,Y+5,46,46));
  TextW:=295;
  if R.Get('add_action','')<>'' then
  begin
    TextW:=246; B:=AddBox(Y);
    if Focused and AddFocused and KeyboardFocusVisible then
      Surface(Box(B.X-1.5,B.Y-1.5,B.W+3,B.H+3),(B.W+3)/2,InkFocus);
    if AddHeld(Control) then Surface(B,B.W/2,InkLine)
    else if HoverAdd=Control then Surface(B,B.W/2,InkRaised)
    else Surface(B,B.W/2,InkPanel);
    if AddConfirmed(Control) then DrawAddCheck(B.X+B.W/2,B.Y+B.H/2)
    else if R.Get('assisted',false) then Chevron(B.X+22,B.Y+22,true,6)
    else begin
      Rect(B.X+14,B.Y+20.5,15,2,InkAccent);
      Rect(B.X+20.5,B.Y+14,2,15,InkAccent);
    end;
  end;
  LabelAt(82,Y+7,17,R.Get('label',''),TextW,false,true);
  LabelAt(82,Y+32,14,R.Get('sub',''),TextW,true);
end;

procedure SearchIcon(X,Y:single);
var I:integer; A,B:single;
begin
  for I:=0 to 15 do
  begin
    A:=2*Pi*I/16; B:=2*Pi*(I+1)/16;
    Renderer.DrawLine(X+5.5*Cos(A),Y+5.5*Sin(A),X+5.5*Cos(B),Y+5.5*Sin(B),0,1.5,InkMuted.R,InkMuted.G,InkMuted.B,1);
  end;
  Renderer.DrawLine(X+4,Y+4,X+9,Y+9,0,1.5,InkMuted.R,InkMuted.G,InkMuted.B,1);
end;

procedure DrawInput(R:TJSONObject; Y:single; Focused:boolean);
var B:TBox; X,Ty,Available,Caret:single; Value:UTF8String; Editing,Query:boolean;
begin
  Query:=SearchField(R); Editing:=Focused and (EditAction=R.Get('action',''));
  if Query then B:=Box(16,Y,368,44)
  else begin
    LabelAt(20,Y+1,14,R.Get('label',''),350,true);
    B:=Box(16,Y+22,368,39);
  end;
  if Editing then FocusInset(B);
  Surface(B,6,InkRaised);
  X:=B.X+12; Ty:=B.Y+(B.H-18)/2;
  if Query then begin SearchIcon(X+5,B.Y+B.H/2-1); X:=X+26; end;
  Available:=B.X+B.W-X-14;
  if Editing then Value:=EditValue+Composition else Value:=R.Get('value','');
  if R.Get('secret',false) then Value:=StringOfChar('*',Length(Value));
  Value:=EditorTail(Value,Available-4);
  Caret:=X+TextWidth(Value);
  if Editing and EditSelectedAll and (Value<>'') then Rect(X-1,Ty-3,Caret-X+3,25,InkLine);
  if Value<>'' then LabelAt(X,Ty,18,Value,Available)
  else if Query then LabelAt(X,Ty,16,R.Get('label','Buscar canciones'),Available,true);
  if Editing and not EditSelectedAll and ((SDL_GetTicks div 530) mod 2=0) then Rect(Caret+1,Ty-1,1.6,21,InkAccent);
end;

procedure DrawControl(R:TJSONObject; Y:single; H:integer; Focused,Hovered:boolean);
var Kind,Style,Sub,Caption,Control: UTF8String; B:TBox; X,Value:single; QR:TTexture;
begin
  Kind:=R.Get('kind',''); Style:=R.Get('style',''); Sub:=R.Get('sub',''); Caption:=R.Get('label','');
  if Kind='qr' then
  begin
    QR:=CachedCover(R.Get('path',''));
    if Assigned(QR) then
    begin
      QR.X:=94; QR.Y:=Y+3; QR.W:=212; QR.H:=212; QR.Z:=0;
      QR.ColR:=1; QR.ColG:=1; QR.ColB:=1; QR.Alpha:=1; QR.Reflection:=false;
      Renderer.DrawTexture(QR);
    end;
    Exit;
  end;
  if Kind='song' then begin SongRow(R,Y,Focused,Hovered); Exit; end;
  if Kind='input' then begin DrawInput(R,Y,Focused); Exit; end;
  if (Style='checked') or (Style='check') then
  begin
    B:=Box(16,Y,368,40); if Focused then FocusInset(B); Surface(B,8,InkPanel);
    Outline(Box(25,Y+13,14,14),0.77,0.79,0.84); if Style='checked' then DrawAddCheck(32,Y+20);
    LabelAt(53,Y+11,15,Caption,310,true); Exit;
  end;
  if Kind='slider' then
  begin
    B:=Box(16,Y,368,H-5);
    if Focused then begin FocusInset(B); Surface(B,6,InkStage); end;
    Value:=EnsureRange(R.Get('value',0.0),0.0,100.0);
    LabelAt(24,Y+3,16,R.Get('label',''),286);
    LabelAt(330,Y+3,14,IntToStr(Round(Value))+'%',48,true);
    Rect(24,Y+35,290,4,InkGuide);
    Rect(24,Y+35,290*Value/100,4,InkAccent);
    Surface(Box(19+290*Value/100,Y+31,12,12),6,InkAccent);
    Exit;
  end;
  if Kind='text' then
  begin
    LabelAt(21,Y+6,17,R.Get('label',''),358,false,true);
    if Sub<>'' then LabelAt(21,Y+30,14,Sub,358,true);
    Exit;
  end;
  B:=Box(16,Y,368,H-6); X:=26;
  Control:=RowAddKey(R.Get('action','')); Caption:=R.Get('label','');
  if Focused and (KeyboardFocusVisible or not AddAction(R.Get('action',''))) then FocusInset(B);
  if (Style='primary') and AddHeld(Control) then Surface(B,6,InkFocus)
  else if Style='primary' then Surface(B,6,InkAccent)
  else if Hovered or Focused then Surface(B,6,InkRaised)
  else if Style='' then Rect(22,Y+H-5,356,1,InkRaised);
  if Style='back' then begin Chevron(X+3,Y+16,false); X:=X+18; end;
  if (Style='link') or (Style='back') then LabelAt(X,Y+9,15,R.Get('label',''),340,true)
  else if Style='primary' then
  begin
    if AddConfirmed(Control) then begin DrawAddCheck(X+8,Y+18); Caption:='En la cola'; end;
    if AddConfirmed(Control) then LabelAt(X+24,Y+9,17,Caption,317,false,true,true)
    else LabelAt(X,Y+9,17,Caption,341,false,true,true);
  end
  else begin
    LabelAt(X,Y+9,16,R.Get('label',''),321);
    Chevron(367,Y+(H-6)/2,true);
  end;
  if Sub<>'' then LabelAt(X,Y+32,14,Sub,330,Style<>'primary',false,Style='primary');
end;

procedure DrawFooter;
var Msg,Line,Word:UTF8String; I,Y:integer;
begin
  Msg:=StatusText; if Msg='' then Exit;
  Y:=Round(Height)-FooterHeight;
  Rect(16,Y,368,1,InkLine); Inc(Y,11); Line:='';
  while (Msg<>'') and (Y<Height-15) do
  begin
    I:=Pos(' ',Msg); if I=0 then I:=Length(Msg)+1;
    Word:=Copy(Msg,1,I-1); Delete(Msg,1,I);
    SetFontStyle(ftRegular); ResetFont; SetFontSize(14);
    if (Line<>'') and (TextWidth(Line+' '+Word)>354) then
    begin LabelAt(22,Y,14,Line,355,true); Inc(Y,19); Line:=Word; end
    else if Line='' then Line:=Word else Line:=Line+' '+Word;
  end;
  if Y<Height-12 then LabelAt(22,Y,14,Line,355,true);
end;

procedure ShellDraw;
var I,Y,RH,W,TopY,BottomY,Total,Avail:integer; A:TJSONArray; R:TJSONObject;
    B:TBox; Value:UTF8String; LabelX,Scale,ThumbH:single;
begin
  if Quitting or not ShellEnabled or not Started then Exit;
  Renderer.SetClipText(false); Renderer.SetScissorTest(false);
  W:=ScreenW-SideWidth;
  if not Singing then
  begin
    Renderer.SetViewPort(0,0,W,ScreenH); Renderer.SetOrthographicProjection(0,W,ScreenH,0,-1,100);
    Renderer.DepthTest:=false; DrawStage(W);
  end;
  if PanelCollapsed then
  begin
    Renderer.SetViewPort(0,0,ScreenW,ScreenH);
    Renderer.SetOrthographicProjection(0,ScreenW,ScreenH,0,-1,100); Renderer.DepthTest:=false;
    B:=RestoreBox; if PanelToggleFocused then FocusInset(B);
    if PanelHover then Surface(B,6,InkRaised) else Surface(B,6,InkPanel);
    Chevron(B.X+14,B.Y+20,false); LabelAt(B.X+30,B.Y+12,15,'Mostrar panel',106);
    Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true; Exit;
  end;
  Renderer.SetViewPort(W,0,SideWidth,ScreenH); Renderer.SetOrthographicProjection(0,400,Height,0,-1,100); Renderer.DepthTest:=false;
  Rect(0,0,400,Height,InkPanel); Rect(0,0,1,Height,InkLine);
  for I:=1 to 3 do
  begin
    B:=TabBox(I); Value:=TabPage(I); if I=3 then Value:='Sesión';
    if (I=2) and Assigned(View) and (View.Get('queue_count',0)>0) then
      Value:=Value+' '+IntToStr(View.Get('queue_count',0));
    if Focus=I-10 then FocusInset(B);
    if Focus=I-10 then Surface(B,7,InkPanel);
    if CurrentTab=I then Rect(B.X+6,B.Y+B.H-1,B.W-12,3,InkAccent);
    SetFontStyle(ftRegular); ResetFont; SetFontSize(15);
    LabelX:=B.X+Max(4.0,(B.W-TextWidth(Value))/2);
    LabelAt(LabelX,B.Y+13,16,Value,B.W-6,I<>CurrentTab);
  end;
  if Assigned(View) and (View.Get('undo','')<>'') then
  begin
    B:=UndoBox; if Focus=-10 then FocusInset(B); Surface(B,7,InkRaised);
    LabelAt(B.X+6,B.Y+13,14,'Deshacer',B.W-10);
  end;
  B:=FoldBox; if Focus=-11 then FocusInset(B);
  if PanelHover or (Focus=-11) then Surface(B,7,InkRaised);
  // Sidebar glyph: a pane divider and a closing chevron.
  Rect(B.X+11,B.Y+11,1.5,16,0.77,0.79,0.84); Chevron(B.X+23,B.Y+19,true,5);
  Rect(16,61,368,1,InkLine);
  if Singing then
  begin
    B:=TransportBox(false); if Focus=-6 then FocusInset(B);
    Surface(B,6,InkRaised);
    if ScreenSing.Paused then Value:='Reanudar' else Value:='Pausar';
    LabelAt(B.X+12,B.Y+10,16,Value,B.W-24);
    B:=TransportBox(true); if Focus=-5 then FocusInset(B);
    if Focus=-5 then Surface(B,6,InkRaised);
    LabelAt(B.X+12,B.Y+10,16,'Terminar canción',B.W-24,true);
  end;
  TopY:=ContentTop; BottomY:=ContentBottom;
  if not MainPage then LabelAt(20,TopY-42,24,Page,360,false,true);
  if Assigned(View) then
  begin
    A:=View.Arrays['rows']; Total:=0;
    for I:=0 to A.Count-1 do Inc(Total,RowHeight(TJSONObject(A[I])));
    Avail:=Max(1,BottomY-TopY); Scroll:=EnsureRange(Scroll,0,Max(0,Total-Avail));
    Y:=TopY-Scroll; Scale:=SideWidth/400;
    Renderer.SetScissorRect(W,Max(0,ScreenH-Round(BottomY*Scale)),SideWidth,Max(1,Round(Avail*Scale)));
    Renderer.SetScissorTest(true);
    for I:=0 to A.Count-1 do
    begin
      R:=TJSONObject(A[I]); RH:=RowHeight(R);
      if (Y+RH>TopY) and (Y<BottomY) then DrawControl(R,Y,RH,Focus=I,Hover=I);
      Inc(Y,RH);
    end;
    Renderer.SetScissorTest(false);
    if Total>Avail then
    begin
      ThumbH:=Max(24.0,Avail*Avail/Total);
      Rect(395,TopY+Scroll*(Avail-ThumbH)/(Total-Avail),2,ThumbH,0.41,0.42,0.46);
    end;
    DrawFooter;
  end;
  Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true;
end;
procedure CommitEdit;
begin
  if EditAction<>'' then
  begin
    if EditAction='field:query' then PublishSearch else Emit(EditAction,EditValue);
    EditAction:=''; EditValue:=''; Composition:='';
  end;
  EditSelectedAll:=false;
  SDL_StopTextInput;
end;
function RowAt(X,Y: single): integer;
var I,P,H: integer; A: TJSONArray;
begin
  Result:=-1; if not Assigned(View) or (X<16) or (X>=384) or (Y<ContentTop) or (Y>=ContentBottom) then Exit;
  A:=View.Arrays['rows']; P:=ContentTop-Scroll;
  for I:=0 to A.Count-1 do begin H:=RowHeight(TJSONObject(A[I])); if (Y>=P) and (Y<P+H-2) and ((TJSONObject(A[I]).Get('kind','')='song') or (Y<P+H-8)) then begin Result:=I; Exit; end; Inc(P,H); end;
end;
procedure SelectRow(I: integer; X: single=24; PointerAction: boolean=false; PointerY: single=0);
var R: TJSONObject; Kind: string; A: TJSONArray; Y,J: integer;
begin
  if not Assigned(View) then Exit;
  A:=View.Arrays['rows']; if (I<0) or (I>=A.Count) then Exit;
  R:=TJSONObject(A[I]);
  if (I=Focus) and (EditAction<>'') and (R.Get('action','')=EditAction) then Exit;
  CommitEdit; Kind:=R.Get('kind','');
  if (Kind='text') or ((R.Get('action','')='') and (R.Get('add_action','')='')) then Exit;
  Focus:=I;
  if PointerAction then
  begin
    Y:=ContentTop-Scroll;
    for J:=0 to I-1 do Inc(Y,RowHeight(TJSONObject(A[J])));
    AddFocused:=(R.Get('add_action','')<>'') and Inside(AddBox(Y),X,PointerY);
  end;
  if Kind='song' then
  begin
    if AddFocused or (R.Get('action','')='') then RequestAdd(R.Get('add_action',''),RowAddKey(R.Get('add_action','')))
    else Emit(R.Get('action',''));
    Exit;
  end;
  if Kind='input' then
  begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); LastSubmitted:=EditValue; Composition:=''; SDL_StartTextInput; end
  else if Kind='button' then begin
    if AddAction(R.Get('action','')) then RequestAdd(R.Get('action',''),RowAddKey(R.Get('action','')))
    else Emit(R.Get('action',''));
  end
  else if (Kind='slider') and PointerAction then Emit(R.Get('action',''),IntToStr(Round(EnsureRange((X-24)/290*100,0.0,100.0))));
end;
procedure OpenTab(I:integer);
var J:integer; A:TJSONArray;
begin
  StageFocused:=false; AddFocused:=false;
  if (I=1) and (Page='Buscar') and Assigned(View) then
  begin
    A:=View.Arrays['rows'];
    for J:=0 to A.Count-1 do if SearchField(TJSONObject(A[J])) then begin SelectRow(J); Exit; end;
  end;
  CommitEdit; Focus:=I-10; Emit('page:'+TabPage(I));
end;
procedure ActivateFocus;
var Action: string;
begin
  if PanelCollapsed and PanelToggleFocused then begin SetPanelCollapsed(false); Exit; end;
  if Focus= -12 then
  begin
    if ShowingResults then ResultsDismissed:=true
    else if Assigned(StageSong) then Emit(StageSong.Get('action',''))
    else begin SetPanelCollapsed(false); Emit('page:Buscar'); end;
    Exit;
  end;
  if PanelCollapsed then begin SetPanelCollapsed(false); Exit; end;
  if Focus= -11 then begin SetPanelCollapsed(true); Exit; end;
  if Focus>=0 then begin SelectRow(Focus); Exit; end;
  Action:=FocusAction;
  if Action<>'' then begin CommitEdit; Emit(Action); end;
end;
procedure MoveFocus(Backwards: boolean);
var Targets: array of integer; A: TJSONArray; R: TJSONObject;
    I,P,OldIndex,Total: integer;
begin
  if PanelCollapsed then
  begin
    if not Singing then
    begin
      StageFocused:=not StageFocused; PanelToggleFocused:=not StageFocused;
      if StageFocused then Focus:=-12 else Focus:=-11;
    end else PanelToggleFocused:=true;
    Exit;
  end;
  if (Focus>=0) and Assigned(View) and (Focus<View.Arrays['rows'].Count) then
  begin
    R:=TJSONObject(View.Arrays['rows'][Focus]);
    if (R.Get('action','')<>'') and (R.Get('add_action','')<>'') then
      if (Backwards and AddFocused) or (not Backwards and not AddFocused) then
      begin AddFocused:=not AddFocused; Exit; end;
  end;
  AddFocused:=false; CommitEdit; StageFocused:=false;
  if Singing then
  begin
    SetLength(Targets,6); Targets[0]:=-11; for I:=1 to 3 do Targets[I]:=I-10;
    Targets[4]:=-6; Targets[5]:=-5;
  end else
  begin SetLength(Targets,5); Targets[0]:=-12; Targets[1]:=-11; for I:=1 to 3 do Targets[I+1]:=I-10; end;
  if Assigned(View) then
  begin
    if View.Get('undo','')<>'' then begin P:=Length(Targets); SetLength(Targets,P+1); Targets[P]:=-10; end;
    A:=View.Arrays['rows'];
    for I:=0 to A.Count-1 do
      if (TJSONObject(A[I]).Get('action','')<>'') or (TJSONObject(A[I]).Get('add_action','')<>'') then
      begin P:=Length(Targets); SetLength(Targets,P+1); Targets[P]:=I; end;
  end;
  OldIndex:=-1;
  for I:=0 to High(Targets) do if Targets[I]=Focus then begin OldIndex:=I; Break; end;
  if Backwards then
  begin if OldIndex<=0 then P:=High(Targets) else P:=OldIndex-1; end
  else P:=(OldIndex+1) mod Length(Targets);
  Focus:=Targets[P]; StageFocused:=Focus=-12;
  if (Focus>=0) and Assigned(View) then
  begin
    A:=View.Arrays['rows']; Total:=0;
    for I:=0 to Focus-1 do Inc(Total,RowHeight(TJSONObject(A[I])));
    if (ContentTop+Total-Scroll<ContentTop-6) or (ContentTop+Total-Scroll+RowHeight(TJSONObject(A[Focus]))>ContentBottom) then Scroll:=Total;
    R:=TJSONObject(A[Focus]); AddFocused:=Backwards and (R.Get('add_action','')<>'');
    if R.Get('kind','')='input' then
    begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); LastSubmitted:=EditValue; Composition:=''; EditSelectedAll:=false; SDL_StartTextInput; end;
  end;
end;
function StagePointer(PX,PY: integer): boolean;
var W: integer;
begin
  W:=ScreenW-SideWidth; Result:=false;
  if Singing or (PX>=W) then Exit;
  if PanelCollapsed and Inside(RestoreBox,PX,PY) then Exit;
  Result:=true; CommitEdit; Focus:=-12; StageFocused:=true; PanelToggleFocused:=false;
  if ShowingResults then
  begin if Inside(ResultButton,PX,PY) then ResultsDismissed:=true; Exit; end;
  if Assigned(StageSong) then
  begin if Inside(HeroButton(W),PX,PY) then Emit(StageSong.Get('action','')); end
  else if ((Page<>'Buscar') or PanelCollapsed) and Inside(EmptyButton,PX,PY) then
  begin SetPanelCollapsed(false); StageFocused:=false; Emit('page:Buscar'); end;
end;
// Resolve the exact visible control again on release: scrolling, sorting, or an
// asynchronous search can replace the song under a stationary pointer.
function PointerAdd(PX,PY:integer; out Action:string; out Row:integer):string;
var W,I,TopY:integer; X,Y:single; R:TJSONObject;
begin
  Action:=''; Result:=''; Row:=-1; W:=ScreenW-SideWidth;
  if PX<W then Exit;
  if PanelCollapsed then Exit;
  X:=(PX-W)*400/SideWidth; Y:=PY*400/SideWidth;
  Row:=RowAt(Round(X),Round(Y)); if Row<0 then Exit;
  R:=TJSONObject(View.Arrays['rows'][Row]); TopY:=ContentTop-Scroll;
  for I:=0 to Row-1 do Inc(TopY,RowHeight(TJSONObject(View.Arrays['rows'][I])));
  if R.Get('kind','')='song' then begin
    if Inside(AddBox(TopY),X,Y) then Action:=R.Get('add_action','');
  end else if (R.Get('kind','')='button') and Inside(Box(16,TopY,368,RowHeight(R)-6),X,Y) then
    Action:=R.Get('action','');
  if AddAction(Action) then Result:=RowAddKey(Action) else Action:='';
end;

function ShellEvent(var Event: TSDL_Event): boolean;
var Action,Control:string; X,Y,P,I: integer; A: TJSONArray; R: TJSONObject; Clip: PAnsiChar; Key: cardinal;
begin
  Result:=false; if not ShellEnabled or not Started then Exit;
  if Quitting then Exit(true);
  if (Event.type_=SDL_QUITEV) or
     ((Event.type_=SDL_WINDOWEVENT) and (Event.window.event=SDL_WINDOWEVENT_CLOSE) and
      (Event.window.windowID=SDL_GetWindowID(screen))) then
  begin RequestQuit; Exit(true); end;
  if (Event.type_=SDL_WINDOWEVENT) and (Event.window.event=SDL_WINDOWEVENT_FOCUS_GAINED) then Display.SetCursor;
  if (Event.type_=SDL_WINDOWEVENT) and
     ((Event.window.event=SDL_WINDOWEVENT_FOCUS_LOST) or (Event.window.event=SDL_WINDOWEVENT_LEAVE)) then
  begin HeldAdd:=''; HoverAdd:=''; end;
  if Event.type_=SDL_MOUSEMOTION then
  begin
    HoverAdd:=PointerAdd(Event.motion.x,Event.motion.y,Action,I);
    X:=Event.motion.x; Y:=Event.motion.y; PanelHover:=false; Hover:=-1;
    if PanelCollapsed then PanelHover:=Inside(RestoreBox,X,Y)
    else if X>=ScreenW-SideWidth then
    begin
      X:=Round((X-ScreenW+SideWidth)*400/SideWidth); Y:=Round(Y*400/SideWidth);
      PanelHover:=Inside(FoldBox,X,Y);
      Hover:=RowAt(X,Y);
    end;
  end;
  if (Event.type_=SDL_MOUSEBUTTONUP) and (Event.button.button=SDL_BUTTON_LEFT) and (HeldAdd<>'') then
  begin
    Control:=PointerAdd(Event.button.x,Event.button.y,Action,I);
    if Control=HeldAdd then RequestAdd(Action,Control);
    HoverAdd:=Control; HeldAdd:=''; Result:=true; Exit;
  end;
  if Event.type_=SDL_MOUSEBUTTONDOWN then
  begin
    KeyboardFocusVisible:=false;
    Control:=PointerAdd(Event.button.x,Event.button.y,Action,I);
    if Control<>'' then begin
      if Event.button.button=SDL_BUTTON_LEFT then begin
        CommitEdit; HeldAdd:=Control; HoverAdd:=Control; StageFocused:=I<0;
        PanelToggleFocused:=false; AddFocused:=(I>=0) and (TJSONObject(View.Arrays['rows'][I]).Get('kind','')='song');
        if I<0 then Focus:=-12 else Focus:=I;
        LastMouseX:=Event.button.x; LastMouseY:=Event.button.y; Inc(MouseClicks);
      end;
      Result:=true; Exit;
    end;
    LastMouseX:=Event.button.x; LastMouseY:=Event.button.y; Inc(MouseClicks);
    if StagePointer(Event.button.x,Event.button.y) then begin Result:=true; Exit; end;
    StageFocused:=false;
    if PanelCollapsed then
    begin
      Result:=true; X:=Event.button.x; Y:=Event.button.y;
      if Inside(RestoreBox,X,Y) then SetPanelCollapsed(false)
      else PanelToggleFocused:=false;
      Exit;
    end;
    X:=Event.button.x; Y:=Round(Event.button.y*400/SideWidth);
    if X>=ScreenW-SideWidth then
    begin
      Result:=true; X:=Round((X-ScreenW+SideWidth)*400/SideWidth);
      if Assigned(View) and (View.Get('undo','')<>'') and Inside(UndoBox,X,Y) then Emit('undo:'+View.Get('undo',''))
      else if Inside(FoldBox,X,Y) then SetPanelCollapsed(true)
      else if (Y>=TabBox(1).Y) and (Y<TabBox(1).Y+TabBox(1).H) then
      begin
        for I:=1 to 3 do if Inside(TabBox(I),X,Y) then
        begin OpenTab(I); Break; end;
      end else if Singing and (Inside(TransportBox(false),X,Y) or Inside(TransportBox(true),X,Y)) then
      begin CommitEdit; if Inside(TransportBox(false),X,Y) then Focus:=-6 else Focus:=-5; ActivateFocus; end
      else SelectRow(RowAt(X,Y),X,true,Y);
    end else begin CommitEdit; Focus:=-1; Result:=true; end;
  end;
  if Event.type_=SDL_MOUSEWHEEL then
  begin
    if PanelCollapsed then begin Result:=true; Exit; end;
    SDL_GetMouseState(@X,@Y);
    if X>=ScreenW-SideWidth then
    begin
      CommitEdit; Focus:=-1;
      if Assigned(View) then
      begin
        A:=View.Arrays['rows']; P:=0; I:=0;
        while (I<A.Count) and (P<Scroll) do begin Inc(P,RowHeight(TJSONObject(A[I]))); Inc(I); end;
        I:=EnsureRange(I-Event.wheel.y,0,Max(0,A.Count-1));
        Scroll:=0; for P:=0 to I-1 do Inc(Scroll,RowHeight(TJSONObject(A[P])));
      end;
      Result:=true;
    end;
  end;
  if (Event.type_=SDL_TEXTEDITING) and not PanelCollapsed and (EditAction<>'') then
  begin Composition:=UTF8String(PAnsiChar(@Event.edit.text[0])); Result:=true; Exit; end;
  if (Event.type_=SDL_TEXTINPUT) and PanelCollapsed then begin Result:=true; Exit; end;
  if (Event.type_=SDL_TEXTINPUT) and (EditAction<>'') then
  begin
    if EditSelectedAll then begin EditValue:=''; EditSelectedAll:=false; end;
    if Length(EditValue)<4096 then EditValue:=EditValue+UTF8String(PAnsiChar(@Event.text.text[0])); EditChanged; Result:=true;
  end;
  if (Event.type_=SDL_KEYDOWN) or (Event.type_=SDL_KEYUP) then
  begin
    Result:=true; if Event.type_=SDL_KEYUP then Exit;
    Key:=Event.key.keysym.sym; KeyboardFocusVisible:=true;
    if (Event.key._repeat<>0) and ((Key=SDLK_RETURN) or (Key=SDLK_PLUS) or (Key=SDLK_SPACE)) and (EditAction='') then Exit;
    if (Event.key.keysym._mod and (KMOD_CTRL or KMOD_GUI))<>0 then
    begin
      if Key=SDLK_q then begin RequestQuit; Exit; end;
      if Key=SDLK_b then begin SetPanelCollapsed(not PanelCollapsed); Exit; end;
      if (Key=SDLK_p) and Singing then begin Emit('pause'); Exit; end;
      if (Key=SDLK_e) and Singing then begin SetPanelCollapsed(false); Emit('end'); Exit; end;
      if (Key>=SDLK_1) and (Key<=SDLK_4) then
      begin
        SetPanelCollapsed(false); OpenTab(Max(1,integer(Key-SDLK_1)));
        Exit;
      end;
      if (Key=SDLK_v) and not PanelCollapsed and (EditAction<>'') then
      begin
        Clip:=SDL_GetClipboardText;
        if Clip<>nil then
        begin
          if EditSelectedAll then EditValue:='';
          EditValue:=Copy(EditValue+UTF8String(Clip),1,4096); EditSelectedAll:=false; SDL_free(Clip); EditChanged;
        end;
      end;
      if (Key=SDLK_a) and not PanelCollapsed and (EditAction<>'') then EditSelectedAll:=true;
      Exit;
    end;
    if not Singing and (EditAction='') and ((Focus=-1) or StageFocused or PanelCollapsed) then
    begin
      if (Key=SDLK_RETURN) and StageFocused then
      begin
        if ShowingResults then ResultsDismissed:=true
        else if Assigned(StageSong) then Emit(StageSong.Get('action',''))
        else begin SetPanelCollapsed(false); Emit('page:Buscar'); end;
        Exit;
      end;
    end;
    if PanelCollapsed then
    begin
      if Key=SDLK_TAB then MoveFocus((Event.key.keysym._mod and KMOD_SHIFT)<>0)
      else if ((Key=SDLK_RETURN) or (Key=SDLK_SPACE)) and PanelToggleFocused then ActivateFocus
      else if (Key=SDLK_SPACE) and Singing then ScreenSing.Pause;
      Exit;
    end;
    if Key=SDLK_TAB then MoveFocus((Event.key.keysym._mod and KMOD_SHIFT)<>0)
    else if EditAction<>'' then
    begin
      if Key=SDLK_BACKSPACE then
      begin if EditSelectedAll then EditValue:='' else TrimLast(EditValue); EditSelectedAll:=false; EditChanged; end;
      if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) then EditSelectedAll:=false;
      if (Key=SDLK_RETURN) and (Composition='') then CommitEdit;
      if (Key=SDLK_ESCAPE) and (EditAction='field:query') and (EditValue<>'') then begin EditValue:=''; EditChanged; PublishSearch; end
      else if Key=SDLK_ESCAPE then begin EditAction:=''; EditValue:=''; EditSelectedAll:=false; Focus:=-1; SDL_StopTextInput; end;
    end
    else if (Key=SDLK_RETURN) or ((Key=SDLK_SPACE) and (Focus<> -1)) then ActivateFocus
    else if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) or (Key=SDLK_PLUS) then
    begin
      if Assigned(View) and (Focus>=0) and (Focus<View.Arrays['rows'].Count) then
      begin R:=TJSONObject(View.Arrays['rows'][Focus]); if (R.Get('kind','')='song') and (R.Get('add_action','')<>'') and (Key<>SDLK_LEFT) then
        begin AddFocused:=true; if Key=SDLK_PLUS then RequestAdd(R.Get('add_action',''),RowAddKey(R.Get('add_action',''))); end
        else if (R.Get('kind','')='song') and (Key=SDLK_LEFT) then AddFocused:=false
        else if (R.Get('kind','')='slider') and (Key<>SDLK_PLUS) then begin I:=5; if Key=SDLK_LEFT then I:=-5; Emit(R.Get('action',''),IntToStr(EnsureRange(R.Get('value',0)+I,0,100))); end; end;
    end
    else if (Key=SDLK_SPACE) and Singing then ScreenSing.Pause;
  end;
end;
end.
