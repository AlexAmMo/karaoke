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
function ShellEvent(var Event: TSDL_Event): boolean;
procedure ShellCaptureStart;
procedure ShellCaptureStop;
implementation
uses SysUtils, Classes, Math, fpjson, jsonparser, UGraphic, UDisplay, URenderer,
  UText, UIni, USongs, USong, UPath, UMusic, URecord, UNote, UScreenSong,
  UCommon, UScreenSingController, UScreenScore, UThemes, UAvatars;
procedure SDL_free(mem: pointer); cdecl; external SDL_LibName name 'SDL_free';
var
  Started: boolean = false;
  View: TJSONObject = nil;
  LastStatus, LastView: cardinal;
  Focus: integer = -1;
  Scroll: integer = 0;
  EditValue, EditAction, Page, ErrorText, Token: UTF8String;
  EditSelectedAll: boolean = false;
  Sequence: integer = 0;
  SynthPosition: int64 = 0;
  SynthTick: cardinal;
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
  ResultsDismissed: boolean = false;
  CoverPaths: array[0..4] of string;
  CoverTextures: array[0..4] of TTexture;

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
    Result:=TJSONObject(View.Arrays['rows'][Focus]).Get('action','');
end;
function ExpandedSideWidth: integer;
begin Result:=Round(EnsureRange(ScreenW*0.34,340.0,440.0)); end;
function SideWidth: integer;
begin if PanelCollapsed then Result:=0 else Result:=ExpandedSideWidth; end;
function Height: single;
begin Result:=ScreenH*400/ExpandedSideWidth; end;
procedure SetPanelCollapsed(Collapsed: boolean);
begin
  if PanelCollapsed=Collapsed then Exit;
  PanelCollapsed:=Collapsed; PanelHover:=false; Hover:=-1; StageFocused:=false;
  // Hiding the panel is not submitting/cancelling an edit. Keep its value and
  // action-based focus while suspending text input until it becomes visible.
  if PanelCollapsed then
  begin PanelToggleFocused:=true; SDL_StopTextInput; LastAction:='panel:hide'; end
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
  else if Op='end' then begin if Singing then ScreenSing.EndSong; end
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
procedure ShellTick;
var J,O: TJSONObject; A,Scores,Devices,Levels: TJSONArray; SR: TSearchRec;
    Commands: TStringList; Forgotten: TSong;
    I,K,N: integer; NowTick: cardinal; Buf: array[0..4095] of SmallInt;
    Frequency: double; Name,FocusKey: string; NewFocus: integer;
begin
  if not ShellEnabled then Exit;
  NowTick:=SDL_GetTicks;
  if not Started then
  begin
    Started:=true; PendingForget:=TStringList.Create; Ini.ScreenFade:=0; Ini.VoicePassthrough:=1; Ini.MicBoost:=0;
    Ini.BackgroundMusicOption:=0; Ini.PreviewVolume:=0; Ini.SavePlayback:=0; Ini.AskbeforeDel:=0;
    Ini.Mouse:=1; SDL_ShowCursor(SDL_ENABLE);
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
        if I=0 then Frequency:=440 else Frequency:=493.883;
        for K:=0 to N-1 do Buf[K]:=Round(8000*Sin(2*Pi*Frequency*(SynthPosition+K)/48000));
        AudioInputProcessor.Sound[I].TestFeed(@Buf[0],N*2);
      end;
      Inc(SynthPosition,N); SynthTick:=NowTick;
    end;
  end;
  if NowTick-LastView>150 then
  begin
    LastView:=NowTick;
    if FileExists(Root+'/view.json') then
    try
      FocusKey:=FocusAction;
      J:=ReadJSON(Root+'/view.json');
      if J.Get('page','')<>Page then
      begin
        Page:=J.Get('page','');
        // Tabs keep their focus on navigation. Page-local controls do not.
        if (Focus< -10) or (Focus> -7) then begin Focus:=-1; StageFocused:=false; FocusKey:=''; end;
        EditAction:=''; EditValue:=''; EditSelectedAll:=false; Scroll:=0; SDL_StopTextInput;
      end;
      View.Free; View:=J;
      // Async rows may be inserted or removed. Preserve the action, never its old index.
      if Focus>=0 then
      begin
        NewFocus:=-1;
        if FocusKey<>'' then for I:=0 to View.Arrays['rows'].Count-1 do
          if TJSONObject(View.Arrays['rows'][I]).Get('action','')=FocusKey then begin NewFocus:=I; Break; end;
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
procedure LabelAt(X,Y,Size: single; const S: UTF8String; Width: single=360; Muted: boolean=false);
var T: UTF8String;
begin
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(Size);
  if Muted then SetFontColor(0.85,0.72,0.76,1) else SetFontColor(0.95,0.95,0.93,1);
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
procedure Surface(X,Y,W,H,R1,G1,B1,R2,G2,B2: single);
var Q: TQuadList;
begin
  SetLength(Q,1);
  Q[0].X:=X; Q[0].Y:=Y; Q[0].Z:=0; Q[0].W:=W; Q[0].H:=H;
  Q[0].Gradient:=gdVertical;
  Q[0].ColR:=R1; Q[0].ColG:=G1; Q[0].ColB:=B1; Q[0].Alpha:=1;
  Q[0].ColR2:=R2; Q[0].ColG2:=G2; Q[0].ColB2:=B2; Q[0].Alpha2:=1;
  Renderer.DrawQuads(Q);
end;
procedure DarkLabel(X,Y,Size: single; const S: UTF8String; Width: single);
begin
  // Measure/truncate with the same font as ordinary labels.
  LabelAt(X,Y,Size,'',Width);
  SetFontColor(0.20,0.06,0.10,1); SetFontPos(X,Y); PrintText(S); Renderer.DepthTest:=false;
end;
function Carousel: TJSONObject;
begin
  Result:=nil;
  if Assigned(View) and (View.Find('carousel') is TJSONObject) then Result:=View.Objects['carousel'];
end;
function HasCarousel: boolean;
begin Result:=Assigned(Carousel) and (Carousel.Arrays['songs'].Count>0); end;
function ShowingResults: boolean;
begin Result:=(Token<>'') and not ResultsDismissed; end;
function CoverSize(W: single): single;
begin Result:=Min(280,Min(W*0.32,ScreenH*0.38)); end;
procedure CoverAt(Song: TJSONObject; Slot: integer; X,Y,S: single; Selected: boolean);
var FileName: string; T: TTexture; Shade: single;
begin
  FileName:=Song.Get('cover','');
  if CoverPaths[Slot]<>FileName then
  begin
    FreeAndNil(CoverTextures[Slot]); CoverPaths[Slot]:=FileName;
    if (FileName<>'') and FileExists(FileName) then
      try CoverTextures[Slot]:=Renderer.LoadTexture(Path(FileName)); except CoverTextures[Slot]:=nil; end;
  end;
  T:=CoverTextures[Slot];
  Shade:=0.75; if Selected then Shade:=1;
  if Selected and StageFocused then Rect(X-4,Y-4,S+8,S+8,1,0.9,0.93);
  if Assigned(T) then
  begin
    T.X:=X; T.Y:=Y; T.W:=S; T.H:=S; T.Z:=0;
    T.ColR:=Shade; T.ColG:=Shade; T.ColB:=Shade; T.Alpha:=1;
    T.Reflection:=not Selected; T.ReflectionSpacing:=5; T.ReflectionHeight:=0.30;
    T.ReflectionAlphaDiff:=0.65;
    Renderer.DrawTexture(T);
  end else
  begin
    Surface(X,Y,S,S,0.34*Shade,0.10*Shade,0.19*Shade,0.12,0.02,0.07);
    LabelAt(X+S*0.08,Y+S*0.50,S*0.09,Song.Get('artist',''),S*0.84);
    LabelAt(X+S*0.08,Y+S*0.65,S*0.065,Song.Get('title',''),S*0.84,true);
    // A plain typographic sleeve denotes missing artwork, never invented album art.
    if not Selected then Surface(X,Y+S+5,S,S*0.25,0.16,0.04,0.08,0.06,0.01,0.03);
  end;
  if Selected then
  begin
    Rect(X,Y+S,S,96,0.71,0.055,0.25);
    LabelAt(X+14,Y+S+14,21,Song.Get('artist',''),S-28);
    LabelAt(X+14,Y+S+43,18,Song.Get('title',''),S-28);
    LabelAt(X+14,Y+S+73,13,'Añadir a la cola',S-28);
    Surface(X,Y+S+101,S,35,0.26,0.025,0.09,0.07,0.012,0.03);
  end;
end;
procedure DrawStage(W: integer);
var C,Song: TJSONObject; Songs: TJSONArray; I,Index,Offset,Depth: integer;
    S,X,Y,NX,NS: single; CountText: string;
begin
  Surface(0,0,W,ScreenH*0.55,0.30,0.025,0.055,0.055,0.008,0.018);
  Surface(0,ScreenH*0.55,W,ScreenH*0.45,0.055,0.008,0.018,0.42,0.035,0.065);
  if ShowingResults then
  begin
    LabelAt(48,48,40,'Tu interpretación',W-96);
    if Assigned(CurrentSong) then LabelAt(48,111,24,CurrentSong.Title,W-96,true);
    for I:=0 to Min(1,High(Player)) do
    begin
      Rect(48,220+I*108,W-96,88,0.49,0.035,0.17);
      LabelAt(68,242+I*108,26,Player[I].Name,W-290);
      LabelAt(W-200,238+I*108,38,IntToStr(Player[I].ScoreTotalInt),145);
    end;
    if StageFocused then Rect(45,ScreenH-167,256,54,1,0.9,0.93);
    Rect(48,ScreenH-164,250,48,0.71,0.055,0.25);
    LabelAt(68,ScreenH-149,18,'Volver al repertorio',210);
  end else
  begin
    LabelAt(48,48,38,'Elige tu canción',W-96);
    C:=Carousel;
    if HasCarousel then
    begin
      Songs:=C.Arrays['songs']; Index:=EnsureRange(C.Get('index',0),0,Songs.Count-1);
      CountText:=IntToStr(C.Get('total',Songs.Count))+' canciones';
      LabelAt(48,104,17,CountText,W-96,true);
      S:=CoverSize(W); X:=(W-S)/2; Y:=Max(156,ScreenH*0.24);
      // Paint farthest sleeves first, then the selected cover above its neighbours.
      for Depth:=2 downto 1 do
      for I:=0 to Songs.Count-1 do
      begin
        Offset:=I-Index;
        if Abs(Offset)=Depth then
        begin
          NS:=S*(0.72-0.12*(Abs(Offset)-1));
          if Offset<0 then NX:=X-NS*0.84-(Abs(Offset)-1)*NS*0.50
          else NX:=X+S-NS*0.16+(Abs(Offset)-1)*NS*0.50;
          Song:=TJSONObject(Songs[I]); CoverAt(Song,I,NX,Y+(S-NS)/2,NS,false);
        end;
      end;
      CoverAt(TJSONObject(Songs[Index]),Index,X,Y,S,true);
      if C.Get('has_previous',false) then Renderer.DrawTriangle(X-26,Y+S/2,X-12,Y+S/2-10,X-12,Y+S/2+10,0,0.94,0.10,0.38,1);
      if C.Get('has_next',false) then Renderer.DrawTriangle(X+S+26,Y+S/2,X+S+12,Y+S/2-10,X+S+12,Y+S/2+10,0,0.94,0.10,0.38,1);
    end else
    begin
      LabelAt(48,ScreenH*0.34,34,'Tu repertorio empieza aquí.',W-96);
      LabelAt(48,ScreenH*0.34+58,20,'Busca una canción con notas o importa tu paquete.',W-96,true);
      if StageFocused then Rect(45,ScreenH*0.34+109,224,54,1,0.9,0.93);
      Rect(48,ScreenH*0.34+112,218,48,0.71,0.055,0.25);
      LabelAt(68,ScreenH*0.34+127,18,'Buscar canciones',178);
      LabelAt(48,ScreenH*0.34+184,17,'La voz original te acompañará al cantar.',W-96,true);
    end;
  end;
  Surface(0,ScreenH-64,W,36,0.98,0.95,0.96,0.60,0.56,0.59);
  DarkLabel(28,ScreenH-53,15,'Karaoke',100);
  if ShowingResults then
  begin
    if Assigned(View) and (View.Get('queue_count',0)>0) then
      DarkLabel(140,ScreenH-53,15,'El siguiente turno te espera en la cola',W-170)
    else DarkLabel(140,ScreenH-53,15,'Elige otra canción para seguir cantando',W-170);
  end
  else if HasCarousel then DarkLabel(140,ScreenH-53,15,'Flechas: elegir     Intro: añadir a la cola',W-170)
  else DarkLabel(140,ScreenH-53,15,'Buscar · Importar · Cantar',W-170);
  if ShellSynthetic then LabelAt(28,ScreenH-22,12,'PRUEBA · Audio sintético, sin micrófono real',W-56,true);
end;
function RowHeight(Row: TJSONObject): integer;
begin if Row.Get('kind','')='input' then Result:=82 else if Row.Get('kind','')='slider' then Result:=74 else if Row.Get('sub','')<>'' then Result:=72 else Result:=48; end;
procedure ShellDraw;
var I,Y,RH,W: integer; A: TJSONArray; R: TJSONObject; Kind,Value,Msg: string; Focused: boolean; V: double;
begin
  if not ShellEnabled or not Started then Exit;
  Renderer.SetClipText(false); Renderer.SetScissorTest(false);
  W:=ScreenW-SideWidth;
  if not Singing then
  begin
    Renderer.SetViewPort(0,0,W,ScreenH); Renderer.SetOrthographicProjection(0,W,ScreenH,0,-1,100); Renderer.DepthTest:=false;
    DrawStage(W);
  end;
  if PanelCollapsed then
  begin
    // A small overlay replaces the entire sidebar; no empty rail reserves space.
    Renderer.SetViewPort(0,0,ScreenW,ScreenH);
    Renderer.SetOrthographicProjection(0,ScreenW,ScreenH,0,-1,100); Renderer.DepthTest:=false;
    if PanelToggleFocused then Rect(ScreenW-173,13,160,46,0.97,0.25,0.48);
    if PanelHover then Rect(ScreenW-170,16,154,40,0.40,0.045,0.15)
    else Rect(ScreenW-170,16,154,40,0.22,0.025,0.08);
    LabelAt(ScreenW-156,28,16,'Mostrar panel',130);
    Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true;
    Exit;
  end;
  Renderer.SetViewPort(W,0,SideWidth,ScreenH); Renderer.SetOrthographicProjection(0,400,Height,0,-1,100); Renderer.DepthTest:=false;
  Rect(0,0,400,Height,0.105,0.012,0.035); Rect(0,0,1,Height,0.37,0.08,0.16);
  LabelAt(22,22,28,'Tu sesión',190);
  if Assigned(View) then
  begin
    Value:=IntToStr(View.Get('queue_count',0));
    if Value='1' then Value:=Value+' turno' else Value:=Value+' turnos';
    LabelAt(220,29,16,Value,90,true);
  end;
  if Focus= -11 then Rect(335,19,52,38,0.97,0.25,0.48);
  if PanelHover then Rect(338,22,46,32,0.40,0.045,0.15)
  else Rect(338,22,46,32,0.22,0.025,0.08);
  Renderer.DrawLine(357,31,364,38,0,2,0.95,0.95,0.93,1);
  Renderer.DrawLine(364,38,357,45,0,2,0.95,0.95,0.93,1);
  for I:=0 to 3 do
  begin
    case I of 0: Value:='Biblioteca'; 1: Value:='Buscar'; 2: Value:='Cola'; 3: Value:='Ajustes'; end;
    if Focus=I-10 then Rect(10+I*96,66,96,40,0.97,0.25,0.48);
    if Page=Value then
    begin
      Rect(12+I*96,68,92,36,0.64,0.035,0.22);
      Rect(12+I*96,102,92,2,0.97,0.25,0.48);
    end
    else Rect(12+I*96,68,92,36,0.105,0.012,0.035);
    LabelAt(19+I*96,78,16,Value,86);
  end;
  if Singing then
  begin
    if Focus= -6 then Rect(13,113,186,42,0.97,0.25,0.48);
    if Focus= -5 then Rect(201,113,186,42,0.97,0.25,0.48);
    Rect(16,116,180,36,0.30,0.025,0.10); LabelAt(30,126,16,'Pausar / continuar',155);
    Rect(204,116,180,36,0.30,0.025,0.10); LabelAt(220,126,16,'Terminar canción',150);
  end else if Assigned(View) and (View.Get('next','')<>'') then LabelAt(22,123,16,View.Get('next',''),360,true)
  else LabelAt(22,123,16,'Todo listo, a tu ritmo.',360,true);
  if Assigned(View) then
  begin
    A:=View.Arrays['rows']; Y:=174-Scroll;
    for I:=0 to A.Count-1 do
    begin
      R:=TJSONObject(A[I]); RH:=RowHeight(R); Kind:=R.Get('kind','');
      if (Y>=168) and (Y+RH<=Height-98) then
      begin
        Focused:=Focus=I;
        if Focused then Rect(13,Y-3,374,RH-2,0.97,0.25,0.48);
        if (Kind='button') or (Kind='input') or Focused then
        begin
          if Hover=I then Rect(16,Y,368,RH-8,0.40,0.045,0.15)
          else Rect(16,Y,368,RH-8,0.22,0.025,0.08);
        end;
        if Kind='text' then LabelAt(24,Y+8,20,R.Get('label',''),350)
        else if Kind='input' then LabelAt(24,Y+8,16,R.Get('label',''),350,true)
        else LabelAt(24,Y+8,18,R.Get('label',''),350);
        if Kind='input' then
        begin
          if Focused and (EditAction<>'') then Value:=EditValue else Value:=R.Get('value','');
          if R.Get('secret',false) then Value:=StringOfChar('*',Length(Value));
          if Focused and EditSelectedAll and (EditAction<>'') then Rect(22,Y+35,350,29,0.60,0.055,0.22)
          else if Focused then Value:=Value+'|';
          if Value='' then LabelAt(24,Y+40,18,'Clic para escribir',345,true)
          else LabelAt(24,Y+40,18,Value,345);
        end
        else if Kind='slider' then
        begin
          V:=R.Get('value',0.0); Rect(24,Y+44,290,8,0.36,0.15,0.21); Rect(24,Y+44,290*V/100,8,0.97,0.25,0.48);
          LabelAt(325,Y+36,16,IntToStr(Round(V))+'%',55);
        end
        else if R.Get('sub','')<>'' then LabelAt(24,Y+36,15,R.Get('sub',''),350,true);
      end;
      Inc(Y,RH);
    end;
    if Scroll>0 then Renderer.DrawTriangle(365,161,370,156,375,161,0,0.85,0.72,0.76,1);
    if Y>Height-98 then Renderer.DrawTriangle(365,Height-110,375,Height-110,370,Height-105,0,0.85,0.72,0.76,1);
    Rect(1,Height-94,399,94,0.15,0.015,0.045);
    Msg:=View.Get('message','');
    if ErrorText<>'' then Msg:=ErrorText;
    // Split by words; no hidden end of status behind a one-line ellipsis.
    Value:=''; Y:=Round(Height-80);
    while (Msg<>'') and (Y<Height-12) do
    begin
      I:=Pos(' ',Msg); if I=0 then I:=Length(Msg)+1;
      Kind:=Copy(Msg,1,I-1); Delete(Msg,1,I);
      SetFontSize(16);
      if TextWidth(Value+' '+Kind)>350 then begin LabelAt(22,Y,16,Value,354,true); Inc(Y,22); Value:=Kind; end
      else if Value='' then Value:=Kind else Value:=Value+' '+Kind;
    end;
    if Y<Height-12 then LabelAt(22,Y,16,Value,354,true);
  end;
  Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true;
end;
procedure CommitEdit;
begin
  if EditAction<>'' then begin Emit(EditAction,EditValue); EditAction:=''; EditValue:=''; end;
  EditSelectedAll:=false;
  SDL_StopTextInput;
end;
function RowAt(Y: single): integer;
var I,P,H: integer; A: TJSONArray;
begin
  Result:=-1; if not Assigned(View) or (Y<168) or (Y>Height-98) then Exit;
  A:=View.Arrays['rows']; P:=174-Scroll;
  for I:=0 to A.Count-1 do begin H:=RowHeight(TJSONObject(A[I])); if (P>=168) and (P+H<=Height-98) and (Y>=P) and (Y<P+H) then begin Result:=I; Exit; end; Inc(P,H); end;
end;
procedure SelectRow(I: integer; X: single=24; PointerAction: boolean=false);
var R: TJSONObject; Kind: string; A: TJSONArray;
begin
  if not Assigned(View) then Exit;
  A:=View.Arrays['rows']; if (I<0) or (I>=A.Count) then Exit;
  CommitEdit; Focus:=I; R:=TJSONObject(A[I]); Kind:=R.Get('kind','');
  if Kind='input' then
  begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); SDL_StartTextInput; end
  else if Kind='button' then Emit(R.Get('action',''))
  else if (Kind='slider') and PointerAction then Emit(R.Get('action',''),IntToStr(Round(EnsureRange((X-24)/290*100,0.0,100.0))));
end;
procedure ActivateFocus;
var Action: string;
begin
  if PanelCollapsed and PanelToggleFocused then begin SetPanelCollapsed(false); Exit; end;
  if Focus= -12 then
  begin
    if ShowingResults then ResultsDismissed:=true
    else if HasCarousel then Emit('carousel:enqueue')
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
  CommitEdit; StageFocused:=false;
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
      if TJSONObject(A[I]).Get('kind','')<>'text' then
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
    if (174+Total-Scroll<168) or (174+Total-Scroll+RowHeight(TJSONObject(A[Focus]))>Height-98) then Scroll:=Total;
    R:=TJSONObject(A[Focus]);
    if R.Get('kind','')='input' then
    begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); EditSelectedAll:=false; SDL_StartTextInput; end;
  end;
end;
function StagePointer(PX,PY: integer): boolean;
var W,I,Index,Offset,Depth: integer; S,X,Y,NS,NX: single; C: TJSONObject; A: TJSONArray;
begin
  Result:=false; W:=ScreenW-SideWidth;
  if Singing or (PX>=W) then Exit;
  if PanelCollapsed and (PX>=ScreenW-170) and (PY>=16) and (PY<=56) then Exit;
  Result:=true; CommitEdit; Focus:=-12; StageFocused:=true; PanelToggleFocused:=false;
  if ShowingResults then
  begin
    if (PX>=48) and (PX<=298) and (PY>=ScreenH-164) and (PY<=ScreenH-116) then ResultsDismissed:=true;
    Exit;
  end;
  if not HasCarousel then
  begin
    if (PX>=48) and (PX<=266) and (PY>=ScreenH*0.34+112) and (PY<=ScreenH*0.34+160) then
    begin SetPanelCollapsed(false); StageFocused:=false; Emit('page:Buscar'); end;
    Exit;
  end;
  C:=Carousel; A:=C.Arrays['songs']; Index:=EnsureRange(C.Get('index',0),0,A.Count-1);
  S:=CoverSize(W); X:=(W-S)/2; Y:=Max(156,ScreenH*0.24);
  if (PX>=X) and (PX<=X+S) and (PY>=Y) and (PY<=Y+S+96) then
  begin Emit('carousel:enqueue'); Exit; end;
  if (PY>=Y) and (PY<=Y+S) then
  begin
    if (PX>=X-34) and (PX<X) then begin Emit('carousel:previous'); Exit; end;
    if (PX>X+S) and (PX<=X+S+34) then begin Emit('carousel:next'); Exit; end;
    // The nearest visible sleeve wins where the perspective overlaps.
    for Offset:=1 to 2 do
      for I:=0 to A.Count-1 do
        if Abs(I-Index)=Offset then
        begin
          NS:=S*(0.72-0.12*(Offset-1));
          if I<Index then NX:=X-NS*0.84-(Offset-1)*NS*0.50
          else NX:=X+S-NS*0.16+(Offset-1)*NS*0.50;
          if (PX>=NX) and (PX<=NX+NS) and (PY>=Y+(S-NS)/2) and (PY<=Y+(S+NS)/2) then
          begin Emit('carousel:select:'+TJSONObject(A[I]).Get('id','')); Exit; end;
        end;
  end;
end;
function ShellEvent(var Event: TSDL_Event): boolean;
var X,Y,P,I: integer; A: TJSONArray; R: TJSONObject; Clip: PAnsiChar; Key: cardinal;
begin
  Result:=false; if not ShellEnabled or not Started then Exit;
  if Event.type_=SDL_MOUSEMOTION then
  begin
    X:=Event.motion.x; Y:=Event.motion.y; PanelHover:=false; Hover:=-1;
    if PanelCollapsed then PanelHover:=(X>=ScreenW-170) and (X<=ScreenW-16) and (Y>=16) and (Y<=56)
    else if X>=ScreenW-SideWidth then
    begin
      X:=Round((X-ScreenW+SideWidth)*400/SideWidth); Y:=Round(Y*400/SideWidth);
      PanelHover:=(X>=338) and (X<=384) and (Y>=22) and (Y<=54);
      Hover:=RowAt(Y);
    end;
  end;
  if Event.type_=SDL_MOUSEBUTTONDOWN then
  begin
    LastMouseX:=Event.button.x; LastMouseY:=Event.button.y; Inc(MouseClicks);
    if StagePointer(Event.button.x,Event.button.y) then begin Result:=true; Exit; end;
    StageFocused:=false;
    if PanelCollapsed then
    begin
      Result:=true; X:=Event.button.x; Y:=Event.button.y;
      if (X>=ScreenW-170) and (X<=ScreenW-16) and (Y>=16) and (Y<=56) then SetPanelCollapsed(false)
      else PanelToggleFocused:=false;
      Exit;
    end;
    X:=Event.button.x; Y:=Round(Event.button.y*400/SideWidth);
    if X>=ScreenW-SideWidth then
    begin
      Result:=true; X:=Round((X-ScreenW+SideWidth)*400/SideWidth);
      if (X>=338) and (X<=384) and (Y>=22) and (Y<=54) then SetPanelCollapsed(true)
      else if (Y>=68) and (Y<=108) then
      begin
        CommitEdit; I:=(X-12) div 96; Focus:=I-10;
        case I of 0: Emit('page:Biblioteca'); 1: Emit('page:Buscar'); 2: Emit('page:Cola'); 3: Emit('page:Ajustes'); end;
      end else if (Y>=116) and (Y<=152) and Singing then
      begin CommitEdit; if X<200 then Focus:=-6 else Focus:=-5; ActivateFocus; end
      else SelectRow(RowAt(Y),X,true);
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
  if (Event.type_=SDL_TEXTINPUT) and PanelCollapsed then begin Result:=true; Exit; end;
  if (Event.type_=SDL_TEXTINPUT) and (EditAction<>'') then
  begin
    if EditSelectedAll then begin EditValue:=''; EditSelectedAll:=false; end;
    if Length(EditValue)<4096 then EditValue:=EditValue+UTF8String(PAnsiChar(@Event.text.text[0])); Result:=true;
  end;
  if (Event.type_=SDL_KEYDOWN) or (Event.type_=SDL_KEYUP) then
  begin
    Result:=true; if Event.type_=SDL_KEYUP then Exit;
    Key:=Event.key.keysym.sym;
    if (Event.key.keysym._mod and (KMOD_CTRL or KMOD_GUI))<>0 then
    begin
      if Key=SDLK_q then begin Display.NextScreenWithCheck:=nil; Display.CheckOK:=true; Exit; end;
      if Key=SDLK_b then begin SetPanelCollapsed(not PanelCollapsed); Exit; end;
      if (Key=SDLK_p) and Singing then begin Emit('pause'); Exit; end;
      if (Key=SDLK_e) and Singing then begin SetPanelCollapsed(false); Emit('end'); Exit; end;
      if (Key>=SDLK_1) and (Key<=SDLK_4) then
      begin
        SetPanelCollapsed(false); CommitEdit; Focus:=integer(Key-SDLK_1)-10;
        StageFocused:=false;
        case Key of SDLK_1: Emit('page:Biblioteca'); SDLK_2: Emit('page:Buscar'); SDLK_3: Emit('page:Cola'); SDLK_4: Emit('page:Ajustes'); end;
        Exit;
      end;
      if (Key=SDLK_v) and not PanelCollapsed and (EditAction<>'') then
      begin
        Clip:=SDL_GetClipboardText;
        if Clip<>nil then
        begin
          if EditSelectedAll then EditValue:='';
          EditValue:=Copy(EditValue+UTF8String(Clip),1,4096); EditSelectedAll:=false; SDL_free(Clip);
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
        else if HasCarousel then Emit('carousel:enqueue')
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
      begin if EditSelectedAll then EditValue:='' else TrimLast(EditValue); EditSelectedAll:=false; end;
      if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) then EditSelectedAll:=false;
      if Key=SDLK_RETURN then CommitEdit;
      if Key=SDLK_ESCAPE then begin EditAction:=''; EditValue:=''; EditSelectedAll:=false; Focus:=-1; SDL_StopTextInput; end;
    end
    else if (Key=SDLK_RETURN) or ((Key=SDLK_SPACE) and (Focus<> -1)) then ActivateFocus
    else if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) then
    begin
      if Assigned(View) and (Focus>=0) and (Focus<View.Arrays['rows'].Count) then
      begin R:=TJSONObject(View.Arrays['rows'][Focus]); if R.Get('kind','')='slider' then begin I:=5; if Key=SDLK_LEFT then I:=-5; Emit(R.Get('action',''),IntToStr(EnsureRange(R.Get('value',0)+I,0,100))); end; end;
    end
    else if (Key=SDLK_SPACE) and Singing then ScreenSing.Pause;
  end;
end;
end.
