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
procedure ShellDrawPitchTrace(Left, Top, Width: real; Track, Singer, Spacing: integer);
function ShellEvent(var Event: TSDL_Event): boolean;
procedure ShellCaptureStart;
procedure ShellCaptureStop;
implementation
uses SysUtils, Classes, Math, fpjson, jsonparser, UGraphic, UDisplay, URenderer,
  UText, UIni, USongs, USong, UPath, UMusic, URecord, UNote, UScreenSong,
  UCommon, UPathUtils, UScreenSingController, UScreenScore, UThemes, UAvatars;
procedure SDL_free(mem: pointer); cdecl; external SDL_LibName name 'SDL_free';
var
  Started: boolean = false;
  View: TJSONObject = nil;
  LastStatus, LastView: cardinal;
  Focus: integer = -1;
  Scroll: integer = 0;
  EditValue, EditAction, Page, ErrorText, Token: UTF8String;
  EditSelectedAll: boolean = false;
  LastSubmitted, Composition: UTF8String;
  LastEditTick: cardinal;
  Sequence: integer = 0;
  SynthPosition: int64 = 0;
  SynthTick: cardinal;
  SynthFrequency: array[0..1] of double = (440, 493.883);
  CaptureTestFrame: boolean;
  Gains: array[0..1] of single;
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
  PitchTraces: array[0..1] of TPitchTrace;

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
    -12: Result:='carousel';
    -11: Result:='panel';
    -10: Result:='page:Biblioteca';
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
  Beat := LyricsState.MidBeatD;
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
    Pitch := AudioInputProcessor.Sound[Singer].DetectedPitch(true);
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

  if Singer = 0 then begin R := 0.34; G := 0.86; B := 1.0; end
  else begin R := 1.0; G := 0.56; B := 0.76; end;
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

procedure ShellCaptureStart;
var I: integer; Fmt: TAudioFormatInfo;
begin
  Fmt:=TAudioFormatInfo.Create(1,48000,asfS16);
  for I:=0 to PlayersPlay-1 do AudioInputProcessor.Sound[I].TestStart(Fmt);
  Fmt.Free; SynthTick:=SDL_GetTicks; SynthPosition:=0;
end;
procedure ShellCaptureStop;
var I: integer;
begin for I:=0 to PlayersPlay-1 do AudioInputProcessor.Sound[I].TestStop; end;
procedure BeginSong(J: TJSONObject);
var I,K,N: integer; Names: TJSONArray; Found: boolean; FileName: string;
begin
  if Singing or Assigned(Display.NextScreen) then begin ErrorText:='Hay una interpretación en curso.'; Exit; end;
  if TestingInput then begin if ShellSynthetic then ShellCaptureStop else AudioInput.CaptureStop; TestingInput:=false; end;
  FileName:=J.Get('chart','');
  if not FileExists(FileName) then begin ErrorText:='No se encuentra el mapa.'; Exit; end;
  if Songs.ShellImport(Path(FileName)) then CatSongs.Refresh;
  Found:=false;
  for I:=0 to High(CatSongs.Song) do
    if CatSongs.Song[I].Path.Append(CatSongs.Song[I].FileName).ToNative=FileName then
    begin
      Names:=J.Arrays['names']; N:=EnsureRange(Names.Count,1,2);
      if not ShellSynthetic then
      begin
        if (AudioInputProcessor.ValidateSettings<>0) or
           (AudioInputProcessor.CheckPlayersConfig(N)<>0) then
        begin ErrorText:='Asigna un canal de micrófono a cada cantante en Ajustes.'; Exit; end;
      end;
      for K := 0 to High(PitchTraces) do PitchTraces[K].Active := false;
      Ini.Players:=N-1; PlayersPlay:=N; SetLength(Player,N);
      for K:=0 to N-1 do
      begin
        Ini.Name[K]:=Names.Strings[K]; Player[K].Name:=Names.Strings[K]; Player[K].Level:=1;
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
var Op: string; I,K,D,C,P: integer;
begin
  Op:=J.Get('op','');
  ErrorText:='';
  if Op='start' then BeginSong(J)
  else if (Op='test-tone') and ShellSynthetic then
  begin
    I := J.Get('player',0);
    if (I >= 0) and (I <= High(SynthFrequency)) then
      SynthFrequency[I] := EnsureRange(J.Get('hz',0.0),0.0,2000.0);
  end
  else if (Op='test-screenshot') and ShellSynthetic then CaptureTestFrame := true
  else if Op='panel' then SetPanelCollapsed(J.Get('collapsed',not PanelCollapsed))
  else if Op='gain' then
  begin
    I:=EnsureRange(J.Get('player',0),0,1);
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
    if TestingInput then begin if ShellSynthetic then ShellCaptureStop else AudioInput.CaptureStop; TestingInput:=false; end
    else begin PlayersPlay:=2; if ShellSynthetic then ShellCaptureStart else AudioInput.CaptureStart; TestingInput:=true; end;
  end
  else if Op='scan' then
  begin
    if Singing then ErrorText:='Espera a terminar para detectar entradas.'
    else begin if TestingInput then begin AudioInput.CaptureStop; TestingInput:=false; end; RefreshAudioInputDevices(aimFull); ErrorText:=''; end;
  end
  else if Op='device' then
  begin
    if Singing then begin ErrorText:='Cambia el micrófono entre canciones.'; Exit; end;
    if TestingInput then begin if ShellSynthetic then ShellCaptureStop else AudioInput.CaptureStop; TestingInput:=false; end;
    D:=J.Get('device',-1); C:=J.Get('channel',-1); P:=J.Get('player',0)+1;
    if (D<0) or (D>High(AudioInputProcessor.DeviceList)) or (P<1) or (P>2) then Exit;
    K:=AudioInputProcessor.DeviceList[D].CfgIndex;
    if (C<0) or (C>High(Ini.InputDeviceConfig[K].ChannelToPlayerMap)) then Exit;
    for D:=0 to High(Ini.InputDeviceConfig) do
      for I:=0 to High(Ini.InputDeviceConfig[D].ChannelToPlayerMap) do
        if Ini.InputDeviceConfig[D].ChannelToPlayerMap[I]=P then Ini.InputDeviceConfig[D].ChannelToPlayerMap[I]:=CHANNEL_OFF;
    Ini.InputDeviceConfig[K].ChannelToPlayerMap[C]:=P;
    Ini.Save; ErrorText:='';
  end
  else if Op='quit' then begin Display.NextScreenWithCheck:=nil; Display.CheckOK:=true; end;
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
    Frequency: double; Name,FocusKey: string; NewFocus: integer; EnterSearch: boolean;
begin
  if not ShellEnabled then Exit;
  NowTick:=SDL_GetTicks;
  if not Started then
  begin
    Started:=true; PendingForget:=TStringList.Create; Ini.ScreenFade:=0; Ini.VoicePassthrough:=1; Ini.MicBoost:=0;
    Ini.BackgroundMusicOption:=0; Ini.PreviewVolume:=0; Ini.SavePlayback:=0; Ini.AskbeforeDel:=0;
    Ini.Mouse:=1; Display.SetCursor;
    SDL_SetWindowTitle(screen,'Karaoke'); SDL_SetWindowMinimumSize(screen,1000,640);
    for I:=0 to 1 do AudioInputProcessor.Sound[I].MonitorGain:=0;
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
  if ShellSynthetic and (Singing or TestingInput) and not Assigned(Display.NextScreen) then
  begin
    N:=Min(4096,Round((NowTick-SynthTick)*48));
    if N>0 then
    begin
      for I:=0 to PlayersPlay-1 do
      begin
        Frequency := SynthFrequency[I];
        for K:=0 to N-1 do Buf[K]:=Round(8000*Sin(2*Pi*Frequency*(SynthPosition+K)/48000));
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
    if TestingInput then for I:=0 to 1 do AudioInputProcessor.Sound[I].AnalyzeBuffer;
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
      J.Add('testing',TestingInput); J.Add('synthetic',ShellSynthetic);
      J.Add('token',Token); J.Add('error',ErrorText);
      if Assigned(CurrentSong) then J.Add('title',CurrentSong.Title) else J.Add('title','');
      J.Add('position',AudioPlayback.Position);
      Scores:=TJSONArray.Create; Levels:=TJSONArray.Create;
      for I:=0 to Min(1,High(Player)) do
      begin
        Scores.Add(Player[I].ScoreTotalInt);
      end;
      for I:=0 to 1 do Levels.Add(AudioInputProcessor.Sound[I].MaxSampleVolume);
      J.Add('scores',Scores); J.Add('levels',Levels);
      A:=TJSONArray.Create; for I:=0 to 1 do A.Add(AudioInputProcessor.Sound[I].Tone); J.Add('tones',A);
      A:=TJSONArray.Create; for I:=0 to 1 do A.Add(AudioInputProcessor.Sound[I].MonitorPeak); J.Add('monitor_peaks',A);
      Devices:=TJSONArray.Create;
      for I:=0 to High(AudioInputProcessor.DeviceList) do
      begin
        O:=TJSONObject.Create;
        O.Add('index',I); O.Add('name',AudioInputProcessor.DeviceList[I].Name);
        O.Add('channels',AudioInputProcessor.DeviceList[I].AudioFormat.Channels);
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
procedure LabelAt(X,Y,Size: single; const S: UTF8String; Width: single=360; Muted: boolean=false; Strong: boolean=false);
var T: UTF8String;
begin
  SetFontFamily(0); if Strong then SetFontStyle(ftBold) else SetFontStyle(ftRegular); ResetFont; SetFontSize(Size);
  if Muted then SetFontColor(0.73,0.75,0.79,1) else SetFontColor(0.97,0.96,0.97,1);
  T:=S;
  if TextWidth(T)>Width then
  begin
    while (Length(T)>0) and (TextWidth(T+'...')>Width) do TrimLast(T);
    T:=T+'...';
  end;
  SetFontPos(X,Y); PrintText(T); Renderer.DepthTest:=false;
end;
procedure Rect(X,Y,W,H: single; R,G,B: single);
begin Renderer.DrawQuad(X,Y,0,W,H,R,G,B,1); end;
function Carousel: TJSONObject;
begin
  Result:=nil;
  if Assigned(View) and (View.Find('carousel') is TJSONObject) then Result:=View.Objects['carousel'];
end;
function HasCarousel: boolean;
begin Result:=Assigned(Carousel) and (Carousel.Arrays['songs'].Count>0); end;
function HeroAddAction: string;
var C:TJSONObject; A:TJSONArray; I:integer;
begin
  Result:=''; if not HasCarousel then Exit;
  C:=Carousel; A:=C.Arrays['songs']; I:=EnsureRange(C.Get('index',0),0,A.Count-1);
  Result:='enqueue:'+TJSONObject(A[I]).Get('id','');
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
procedure Surface(const B: TBox; Radius,R,G,Blue: single);
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

procedure FocusInset(const B:TBox);
begin
  Surface(Box(B.X-1,B.Y-1,B.W+2,B.H+2),7,0.99,0.66,0.78);
end;

procedure Chevron(X,Y: single; Right: boolean; Size: single=4);
var DX: single;
begin
  DX:=Size; if not Right then DX:=-Size;
  Renderer.DrawLine(X-DX/2,Y-Size,X+DX/2,Y,0,1.5,0.77,0.79,0.84,1);
  Renderer.DrawLine(X+DX/2,Y,X-DX/2,Y+Size,0,1.5,0.77,0.79,0.84,1);
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
function SleeveBox(W: single; I: integer): TBox;
var S: single;
begin S:=Min(78,(W-120)/5-10); Result:=Box(40+I*(S+12),ScreenH-61-S,S,S); end;
function ArrowBox(W: single; Next: boolean): TBox;
begin Result:=Box(W-124+Ord(Next)*46,ScreenH-105,40,40); end;
procedure DrawArrow(const B: TBox; Next: boolean);
var D,X,Y: single;
begin
  Fill(B,0.15,0.15,0.17);
  D:=-1; if Next then D:=1;
  X:=B.X+B.W/2; Y:=B.Y+B.H/2;
  Renderer.DrawLine(X-D*3,Y-6,X+D*3,Y,0,2,0.95,0.94,0.94,1);
  Renderer.DrawLine(X+D*3,Y,X-D*3,Y+6,0,2,0.95,0.94,0.94,1);
end;
procedure DrawAddCheck(X,Y:single);
begin
  Renderer.DrawLine(X-7,Y,X-2,Y+5,0,2.2,1,0.91,0.94,1);
  Renderer.DrawLine(X-2,Y+5,X+7,Y-5,0,2.2,1,0.91,0.94,1);
end;
procedure PrimaryButton(const B: TBox; const Caption: UTF8String; Focused: boolean);
begin
  if Focused then FocusInset(B);
  Surface(B,7,0.67,0.09,0.31);
  LabelAt(B.X+17,B.Y+13,16,Caption,B.W-32,false,true);
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
    if I<3 then Surface(Box(P,Y+Tones[I]*14-3,Lengths[I],7),3,0.87,0.30,0.51)
    else Surface(Box(P,Y+Tones[I]*14-3,Lengths[I],7),3,0.42,0.30,0.40);
    P:=P+Lengths[I]+9;
  end;
end;
procedure DrawStage(W: integer);
var C,Song: TJSONObject; Songs: TJSONArray; I,Index: integer;
    Art,B: TBox; X,TextW,TitleSize,Y: single; CountText: string;
begin
  Rect(0,0,W,ScreenH,0.076,0.080,0.100);
  if ShowingResults then
  begin
    LabelAt(40,36,18,'Puntuación',W-80,true);
    if Assigned(CurrentSong) then begin
      TitleAt(40,79,Min(42,W/16),W-80,CurrentSong.Title);
      LabelAt(40,186,21,CurrentSong.Artist,W-80,true);
    end;
    for I:=0 to Min(1,High(Player)) do
    begin
      Y:=244+I*95;
      Rect(40,Y,W-80,1,0.22,0.23,0.26);
      Rect(40,Y+25,3,36,0.92,0.39,0.60);
      LabelAt(59,Y+29,23,Player[I].Name,W-270,false,true);
      LabelAt(W-193,Y+17,40,IntToStr(Player[I].ScoreTotalInt),152,false,true);
    end;
    if Assigned(View) then LabelAt(40,ResultButton.Y-41,16,View.Get('next',''),W-80,true);
    PrimaryButton(ResultButton,'Volver al repertorio',StageFocused);
  end else if HasCarousel then
  begin
    C:=Carousel; Songs:=C.Arrays['songs']; Index:=EnsureRange(C.Get('index',0),0,Songs.Count-1);
    LabelAt(40,32,18,'Mi repertorio',W-80,true);
    Song:=TJSONObject(Songs[Index]); Art:=HeroArt(W); Artwork(Song,Art);
    B:=HeroButton(W); X:=B.X; TextW:=W-X-34; TitleSize:=Min(45,TextW/6.3);
    LabelAt(X,Art.Y+Art.H*0.17,Min(20,TextW/10),Song.Get('artist',''),TextW,true);
    TitleAt(X,Art.Y+Art.H*0.30,TitleSize,TextW,Song.Get('title',''));
    if StageFocused and KeyboardFocusVisible then FocusInset(B);
    if AddHeld('hero/'+HeroAddAction) then Surface(B,7,0.52,0.08,0.25)
    else Surface(B,7,0.67,0.09,0.31);
    if AddConfirmed('hero/'+HeroAddAction) then
    begin DrawAddCheck(B.X+23,B.Y+B.H/2); LabelAt(B.X+39,B.Y+13,16,'En la cola',B.W-47,false,true); end
    else LabelAt(B.X+17,B.Y+13,16,'Añadir a la cola',B.W-25,false,true);
    CountText:=IntToStr(C.Get('total',Songs.Count));
    if CountText='1' then CountText:=CountText+' canción' else CountText:=CountText+' canciones';
    Rect(40,SleeveBox(W,0).Y-44,W-80,1,0.18,0.19,0.22);
    LabelAt(40,SleeveBox(W,0).Y-31,14,CountText,W-80,true);
    for I:=0 to Songs.Count-1 do
    begin
      B:=SleeveBox(W,I); Artwork(TJSONObject(Songs[I]),B);
      if I=Index then Rect(B.X,B.Y+B.H+5,B.W,2,0.98,0.30,0.52);
    end;
    if C.Get('has_previous',false) then DrawArrow(ArrowBox(W,false),false);
    if C.Get('has_next',false) then DrawArrow(ArrowBox(W,true),true);
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
  case I of 0:Result:='Biblioteca'; 1:Result:='Buscar'; 2:Result:='Cola'; else Result:='Ajustes'; end;
end;

function MainPage: boolean;
begin Result:=(Page='Biblioteca') or (Page='Buscar') or (Page='Cola') or (Page='Ajustes'); end;

function CurrentTab: integer;
begin
  if MainPage then begin
    for Result:=0 to 3 do if TabPage(Result)=Page then Exit;
  end;
  if (Page='Ediciones') or (Page='Versión') or (Page='Otros catálogos') then Result:=1
  else if (Page='Turno') or (Page='Preparaciones') or (Page='Terminar canción') then Result:=2
  else if (Page='Micrófonos') or (Page='Descargas') or (Page='Móviles') or (Page='Cuenta USDB') or (Page='Entrada 1') or (Page='Entrada 2') then Result:=3
  else Result:=0;
end;

function TabBox(I:integer):TBox;
const Left:array[0..3] of integer=(12,108,186,262);
      Widths:array[0..3] of integer=(92,74,72,76);
begin Result:=Box(Left[I],14,Widths[I],36); end;
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
begin Result:=Box(337,Y+9,43,43); end;
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
  if (Focused and not AddFocused) or (Hovered and (HoverAdd<>Control)) then Surface(B,6,0.18,0.19,0.22)
  else Rect(82,Y+58,296,1,0.19,0.20,0.23);
  Artwork(R,Box(22,Y+5,46,46));
  TextW:=295;
  if R.Get('add_action','')<>'' then
  begin
    TextW:=246; B:=AddBox(Y);
    if Focused and AddFocused and KeyboardFocusVisible then
      Surface(Box(B.X-1.5,B.Y-1.5,B.W+3,B.H+3),(B.W+3)/2,0.99,0.66,0.78);
    if AddHeld(Control) then Surface(B,B.W/2,0.35,0.19,0.27)
    else if HoverAdd=Control then Surface(B,B.W/2,0.30,0.21,0.27)
    else Surface(B,B.W/2,0.22,0.18,0.23);
    if AddConfirmed(Control) then DrawAddCheck(B.X+B.W/2,B.Y+B.H/2)
    else begin
      Rect(B.X+14,B.Y+20.5,15,2,1,0.76,0.83);
      Rect(B.X+20.5,B.Y+14,2,15,1,0.76,0.83);
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
    Renderer.DrawLine(X+5.5*Cos(A),Y+5.5*Sin(A),X+5.5*Cos(B),Y+5.5*Sin(B),0,1.5,0.79,0.80,0.85,1);
  end;
  Renderer.DrawLine(X+4,Y+4,X+9,Y+9,0,1.5,0.79,0.80,0.85,1);
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
  Surface(B,6,0.18,0.19,0.22);
  X:=B.X+12; Ty:=B.Y+(B.H-18)/2;
  if Query then begin SearchIcon(X+5,B.Y+B.H/2-1); X:=X+26; end;
  Available:=B.X+B.W-X-14;
  if Editing then Value:=EditValue+Composition else Value:=R.Get('value','');
  if R.Get('secret',false) then Value:=StringOfChar('*',Length(Value));
  Value:=EditorTail(Value,Available-4);
  Caret:=X+TextWidth(Value);
  if Editing and EditSelectedAll and (Value<>'') then Rect(X-1,Ty-3,Caret-X+3,25,0.49,0.15,0.32);
  if Value<>'' then LabelAt(X,Ty,18,Value,Available)
  else if Query then LabelAt(X,Ty,16,R.Get('label','Buscar canciones'),Available,true);
  if Editing and not EditSelectedAll and ((SDL_GetTicks div 530) mod 2=0) then Rect(Caret+1,Ty-1,1.6,21,1,0.71,0.81);
end;

procedure DrawControl(R:TJSONObject; Y:single; H:integer; Focused,Hovered:boolean);
var Kind,Style,Sub,Caption,Control: UTF8String; B:TBox; X,Value:single; QR:TTexture;
begin
  Kind:=R.Get('kind',''); Style:=R.Get('style',''); Sub:=R.Get('sub','');
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
  if Kind='slider' then
  begin
    B:=Box(16,Y,368,H-5);
    if Focused then begin FocusInset(B); Surface(B,6,0.13,0.14,0.17); end;
    Value:=EnsureRange(R.Get('value',0.0),0.0,100.0);
    LabelAt(24,Y+3,16,R.Get('label',''),286);
    LabelAt(330,Y+3,14,IntToStr(Round(Value))+'%',48,true);
    Rect(24,Y+35,290,4,0.27,0.28,0.32);
    Rect(24,Y+35,290*Value/100,4,0.92,0.39,0.60);
    Surface(Box(19+290*Value/100,Y+31,12,12),6,1,0.78,0.86);
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
  if (Style='primary') and AddHeld(Control) then Surface(B,6,0.52,0.08,0.25)
  else if Style='primary' then Surface(B,6,0.63,0.085,0.29)
  else if Hovered or Focused then Surface(B,6,0.19,0.20,0.23)
  else if Style='' then Rect(22,Y+H-5,356,1,0.18,0.19,0.22);
  if Style='back' then begin Chevron(X+3,Y+16,false); X:=X+18; end;
  if (Style='link') or (Style='back') then LabelAt(X,Y+9,15,R.Get('label',''),340,true)
  else if Style='primary' then
  begin
    if AddConfirmed(Control) then begin DrawAddCheck(X+8,Y+18); Caption:='En la cola'; end;
    if AddConfirmed(Control) then LabelAt(X+24,Y+9,17,Caption,317,false,true)
    else LabelAt(X,Y+9,17,Caption,341,false,true);
  end
  else begin
    LabelAt(X,Y+9,16,R.Get('label',''),321);
    Chevron(367,Y+(H-6)/2,true);
  end;
  if Sub<>'' then LabelAt(X,Y+32,14,Sub,330,true);
end;

procedure DrawFooter;
var Msg,Line,Word:UTF8String; I,Y:integer;
begin
  Msg:=StatusText; if Msg='' then Exit;
  Y:=Round(Height)-FooterHeight;
  Rect(16,Y,368,1,0.21,0.22,0.25); Inc(Y,11); Line:='';
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
  if not ShellEnabled or not Started then Exit;
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
    if PanelHover then Surface(B,6,0.23,0.24,0.27) else Surface(B,6,0.14,0.15,0.18);
    Chevron(B.X+14,B.Y+20,false); LabelAt(B.X+30,B.Y+12,15,'Mostrar panel',106);
    Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true; Exit;
  end;
  Renderer.SetViewPort(W,0,SideWidth,ScreenH); Renderer.SetOrthographicProjection(0,400,Height,0,-1,100); Renderer.DepthTest:=false;
  Rect(0,0,400,Height,0.105,0.115,0.14); Rect(0,0,1,Height,0.22,0.23,0.26);
  for I:=0 to 3 do
  begin
    B:=TabBox(I); Value:=TabPage(I);
    if (I=2) and Assigned(View) and (View.Get('queue_count',0)>0) then
      Value:=Value+' '+IntToStr(View.Get('queue_count',0));
    if Focus=I-10 then FocusInset(B);
    if CurrentTab=I then Surface(B,7,0.26,0.205,0.26)
    else if Focus=I-10 then Surface(B,7,0.14,0.15,0.18);
    SetFontStyle(ftRegular); ResetFont; SetFontSize(15);
    LabelX:=B.X+Max(4.0,(B.W-TextWidth(Value))/2);
    LabelAt(LabelX,B.Y+10,15,Value,B.W-6,I<>CurrentTab);
  end;
  B:=FoldBox; if Focus=-11 then FocusInset(B);
  if PanelHover or (Focus=-11) then Surface(B,7,0.20,0.21,0.24);
  // Sidebar glyph: a pane divider and a closing chevron.
  Rect(B.X+11,B.Y+11,1.5,16,0.77,0.79,0.84); Chevron(B.X+23,B.Y+19,true,5);
  Rect(16,61,368,1,0.22,0.23,0.26);
  if Singing then
  begin
    B:=TransportBox(false); if Focus=-6 then FocusInset(B);
    Surface(B,6,0.23,0.19,0.24);
    if ScreenSing.Paused then Value:='Reanudar' else Value:='Pausar';
    LabelAt(B.X+12,B.Y+10,16,Value,B.W-24);
    B:=TransportBox(true); if Focus=-5 then FocusInset(B);
    if Focus=-5 then Surface(B,6,0.18,0.19,0.22);
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
    else if HasCarousel then RequestAdd(HeroAddAction,'hero/'+HeroAddAction)
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
    SetLength(Targets,7); for I:=0 to 4 do Targets[I]:=I-11;
    Targets[5]:=-6; Targets[6]:=-5;
  end else
  begin SetLength(Targets,6); for I:=0 to 5 do Targets[I]:=I-12; end;
  if Assigned(View) then
  begin
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
var W,I: integer; C: TJSONObject; A: TJSONArray;
begin
  W:=ScreenW-SideWidth; Result:=false;
  if Singing or (PX>=W) then Exit;
  if PanelCollapsed and Inside(RestoreBox,PX,PY) then Exit;
  Result:=true; CommitEdit; Focus:=-12; StageFocused:=true; PanelToggleFocused:=false;
  if ShowingResults then
  begin if Inside(ResultButton,PX,PY) then ResultsDismissed:=true; Exit; end;
  if not HasCarousel then
  begin
    if ((Page<>'Buscar') or PanelCollapsed) and Inside(EmptyButton,PX,PY) then
    begin SetPanelCollapsed(false); StageFocused:=false; Emit('page:Buscar'); end;
    Exit;
  end;
  C:=Carousel; A:=C.Arrays['songs'];
  if C.Get('has_previous',false) and Inside(ArrowBox(W,false),PX,PY) then Emit('carousel:previous')
  else if C.Get('has_next',false) and Inside(ArrowBox(W,true),PX,PY) then Emit('carousel:next')
  else for I:=0 to A.Count-1 do if Inside(SleeveBox(W,I),PX,PY) then
  begin Emit('carousel:select:'+TJSONObject(A[I]).Get('id','')); Exit; end;
end;
// Resolve the exact visible control again on release: scrolling, sorting, or an
// asynchronous search can replace the song under a stationary pointer.
function PointerAdd(PX,PY:integer; out Action:string; out Row:integer):string;
var W,I,TopY:integer; X,Y:single; R:TJSONObject;
begin
  Action:=''; Result:=''; Row:=-1; W:=ScreenW-SideWidth;
  if PX<W then begin
    if not Singing and not ShowingResults and HasCarousel and Inside(HeroButton(W),PX,PY) then
    begin Action:=HeroAddAction; Result:='hero/'+Action; end;
    Exit;
  end;
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
      if Inside(FoldBox,X,Y) then SetPanelCollapsed(true)
      else if (Y>=TabBox(0).Y) and (Y<TabBox(0).Y+TabBox(0).H) then
      begin
        for I:=0 to 3 do if Inside(TabBox(I),X,Y) then
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
      if Key=SDLK_q then begin Display.NextScreenWithCheck:=nil; Display.CheckOK:=true; Exit; end;
      if Key=SDLK_b then begin SetPanelCollapsed(not PanelCollapsed); Exit; end;
      if (Key=SDLK_p) and Singing then begin Emit('pause'); Exit; end;
      if (Key=SDLK_e) and Singing then begin SetPanelCollapsed(false); Emit('end'); Exit; end;
      if (Key>=SDLK_1) and (Key<=SDLK_4) then
      begin
        SetPanelCollapsed(false); OpenTab(integer(Key-SDLK_1));
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
      if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) then
      begin
        ResultsDismissed:=true; StageFocused:=true; PanelToggleFocused:=false; Focus:=-12;
        if Key=SDLK_LEFT then Emit('carousel:previous') else Emit('carousel:next'); Exit;
      end;
      if (Key=SDLK_RETURN) and StageFocused then
      begin
        if ShowingResults then ResultsDismissed:=true
        else if HasCarousel then RequestAdd(HeroAddAction,'hero/'+HeroAddAction)
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
      if Key=SDLK_ESCAPE then begin EditAction:=''; EditValue:=''; EditSelectedAll:=false; Focus:=-1; SDL_StopTextInput; end;
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
