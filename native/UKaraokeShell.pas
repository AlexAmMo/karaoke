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
  AddFocused: boolean = false;
  ResultsDismissed: boolean = false;
  CoverTimes: array[0..31] of qword;
  CoverUse: qword = 0;
  CoverPaths: array[0..31] of string;
  CoverTextures: array[0..31] of TTexture;

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
procedure LabelAt(X,Y,Size: single; const S: UTF8String; Width: single=360; Muted: boolean=false);
var T: UTF8String;
begin
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(Size);
  if Muted then SetFontColor(0.72,0.72,0.75,1) else SetFontColor(0.97,0.96,0.97,1);
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
  S:=Min(396,Min(W*0.45,ScreenH*0.425));
  Result:=Box(40,Max(110,(ScreenH-122-S)/2),S,S);
end;
function HeroButton(W: single): TBox;
var Art: TBox;
begin Art:=HeroArt(W); Result:=Box(Art.X+Art.W+28,Art.Y+Art.H*0.67,Min(178,W-Art.X-Art.W-60),44); end;
function EmptyButton: TBox;
begin Result:=Box(40,ScreenH*0.46+94,218,46); end;
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
procedure PrimaryButton(const B: TBox; const Caption: UTF8String; Focused: boolean);
begin
  Fill(B,0.64,0.08,0.28);
  if Focused then Outline(B,1,0.72,0.82);
  LabelAt(B.X+16,B.Y+13,17,Caption,B.W-28);
end;
procedure TitleAt(X,Y,Size,W: single; const Title: UTF8String);
var Line,Rest: UTF8String; I,Cut: integer;
begin
  SetFontFamily(0); SetFontStyle(ftRegular); ResetFont; SetFontSize(Size);
  if TextWidth(Title)<=W then begin LabelAt(X,Y,Size,Title,W); Exit; end;
  Rest:=Title; Line:=''; Cut:=0;
  for I:=1 to Length(Title) do if Title[I]=' ' then
  begin
    if TextWidth(Copy(Title,1,I-1))>W then Break;
    Cut:=I;
  end;
  if Cut=0 then begin LabelAt(X,Y,Size,Title,W); Exit; end;
  Line:=Copy(Title,1,Cut-1); Delete(Rest,1,Cut);
  LabelAt(X,Y,Size,Line,W); LabelAt(X,Y+Size*1.20,Size,Rest,W);
end;
procedure DrawStage(W: integer);
var C,Song: TJSONObject; Songs: TJSONArray; I,Index: integer;
    Art,B: TBox; X,TextW,TitleSize: single; CountText: string;
begin
  Rect(0,0,W,ScreenH,0.080,0.080,0.091);
  if ShowingResults then
  begin
    LabelAt(40,33,34,'Tu interpretación',W-80);
    if Assigned(CurrentSong) then LabelAt(40,89,22,CurrentSong.Title,W-80,true);
    for I:=0 to Min(1,High(Player)) do
    begin
      Rect(40,178+I*106,W-80,1,0.22,0.22,0.24);
      LabelAt(40,206+I*106,25,Player[I].Name,W-270);
      LabelAt(W-192,195+I*106,42,IntToStr(Player[I].ScoreTotalInt),152);
    end;
    PrimaryButton(ResultButton,'Volver al repertorio',StageFocused);
  end else if HasCarousel then
  begin
    C:=Carousel; Songs:=C.Arrays['songs']; Index:=EnsureRange(C.Get('index',0),0,Songs.Count-1);
    LabelAt(40,33,30,'Mi repertorio',W-80);
    CountText:=IntToStr(C.Get('total',Songs.Count));
    if CountText='1' then CountText:=CountText+' canción' else CountText:=CountText+' canciones';
    LabelAt(40,78,16,CountText,W-80,true);
    Song:=TJSONObject(Songs[Index]); Art:=HeroArt(W); Artwork(Song,Art);
    B:=HeroButton(W); X:=B.X; TextW:=W-X-34; TitleSize:=Min(39,TextW/7.5);
    TitleAt(X,Art.Y+Art.H*0.13,TitleSize,TextW,Song.Get('title',''));
    LabelAt(X,Art.Y+Art.H*0.49,Min(22,TextW/10),Song.Get('artist',''),TextW,true);
    PrimaryButton(B,'Añadir a la cola',StageFocused);
    for I:=0 to Songs.Count-1 do
    begin
      B:=SleeveBox(W,I); Artwork(TJSONObject(Songs[I]),B);
      if I=Index then Rect(B.X,B.Y+B.H+5,B.W,3,0.98,0.30,0.52);
    end;
    if C.Get('has_previous',false) then DrawArrow(ArrowBox(W,false),false);
    if C.Get('has_next',false) then DrawArrow(ArrowBox(W,true),true);
  end else
  begin
    LabelAt(40,33,30,'Mi repertorio',W-80);
    LabelAt(40,ScreenH*0.46-16,36,'Tu primera canción',W-80);
    LabelAt(40,ScreenH*0.46+47,19,'Busca una canción con notas o importa una carpeta.',W-80,true);
    PrimaryButton(EmptyButton,'Buscar canciones',StageFocused);
  end;
  if ShellSynthetic then LabelAt(40,ScreenH-22,12,'PRUEBA · Audio sintético, sin micrófono real',W-80,true);
end;
function RowHeight(Row: TJSONObject): integer;
begin if Row.Get('kind','')='song' then Result:=62 else if Row.Get('kind','')='input' then Result:=74 else if Row.Get('kind','')='slider' then Result:=74 else if Row.Get('sub','')<>'' then Result:=72 else Result:=48; end;
function ContentTop: integer;
begin
  if Singing or (Assigned(View) and (View.Get('next','')<>'')) then Result:=166
  else Result:=118;
end;
function AddBox(Y: single): TBox;
begin Result:=Box(340,Y+10,38,38); end;
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
var B: TBox; TextW: single;
begin
  if Hovered or Focused then Rect(16,Y,368,60,0.153,0.154,0.172)
  else Rect(16,Y+60,368,1,0.17,0.17,0.19);
  Artwork(R,Box(22,Y+6,48,48));
  TextW:=295;
  if R.Get('add_action','')<>'' then
  begin
    B:=AddBox(Y); TextW:=252; Fill(B,0.22,0.18,0.22);
    if Focused and AddFocused then Outline(B,1,0.66,0.78);
    Rect(B.X+11,B.Y+18,16,2,1,0.83,0.89); Rect(B.X+18,B.Y+11,2,16,1,0.83,0.89);
  end;
  LabelAt(82,Y+8,18,R.Get('label',''),TextW);
  LabelAt(82,Y+34,14,R.Get('sub',''),TextW,true);
  if Focused and not AddFocused then Outline(Box(16,Y,368,60),0.99,0.57,0.72);
end;
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
    if PanelHover then Rect(ScreenW-170,16,154,40,0.21,0.21,0.24)
    else Rect(ScreenW-170,16,154,40,0.153,0.154,0.172);
    LabelAt(ScreenW-156,28,16,'Mostrar panel',130);
    Renderer.SetOrthographicProjection(0,RenderW,RenderH,0,-1,100); Renderer.DepthTest:=true;
    Exit;
  end;
  Renderer.SetViewPort(W,0,SideWidth,ScreenH); Renderer.SetOrthographicProjection(0,400,Height,0,-1,100); Renderer.DepthTest:=false;
  Rect(0,0,400,Height,0.105,0.106,0.119); Rect(0,0,1,Height,0.22,0.22,0.24);
  LabelAt(22,22,28,'Tu sesión',190);
  if Assigned(View) then
  begin
    Value:=IntToStr(View.Get('queue_count',0));
    if Value='1' then Value:=Value+' turno' else Value:=Value+' turnos';
    LabelAt(220,29,16,Value,90,true);
  end;
  if Focus= -11 then Rect(335,19,52,38,0.97,0.25,0.48);
  if PanelHover then Rect(338,22,46,32,0.21,0.21,0.24)
  else Rect(338,22,46,32,0.153,0.154,0.172);
  Renderer.DrawLine(357,31,364,38,0,2,0.95,0.95,0.93,1);
  Renderer.DrawLine(364,38,357,45,0,2,0.95,0.95,0.93,1);
  for I:=0 to 3 do
  begin
    case I of 0: Value:='Biblioteca'; 1: Value:='Buscar'; 2: Value:='Cola'; 3: Value:='Ajustes'; end;
    if Focus=I-10 then Rect(10+I*96,66,96,40,0.97,0.25,0.48);
    if Page=Value then
    begin
      Rect(12+I*96,68,92,36,0.18,0.16,0.19);
      Rect(12+I*96,102,92,2,0.97,0.25,0.48);
    end
    else Rect(12+I*96,68,92,36,0.105,0.106,0.119);
    LabelAt(19+I*96,78,16,Value,86);
  end;
  if Singing then
  begin
    if Focus= -6 then Rect(13,113,186,42,0.97,0.25,0.48);
    if Focus= -5 then Rect(201,113,186,42,0.97,0.25,0.48);
    Rect(16,116,180,36,0.19,0.18,0.20); LabelAt(30,126,16,'Pausar / continuar',155);
    Rect(204,116,180,36,0.19,0.18,0.20); LabelAt(220,126,16,'Terminar canción',150);
  end else if Assigned(View) and (View.Get('next','')<>'') then LabelAt(22,123,16,View.Get('next',''),360,true);
  if Assigned(View) then
  begin
    A:=View.Arrays['rows']; Y:=ContentTop-Scroll;
    for I:=0 to A.Count-1 do
    begin
      R:=TJSONObject(A[I]); RH:=RowHeight(R); Kind:=R.Get('kind','');
      if (Y>=ContentTop-6) and (Y+RH<=Height-98) then
      begin
        Focused:=Focus=I;
        if Kind='song' then SongRow(R,Y,Focused,Hover=I)
        else begin
        if Focused then Rect(13,Y-3,374,RH-2,0.97,0.25,0.48);
        if (Kind='button') or (Kind='input') or Focused then
        begin
          if Hover=I then Rect(16,Y,368,RH-8,0.21,0.21,0.24)
          else Rect(16,Y,368,RH-8,0.153,0.154,0.172);
        end;
        if Kind='text' then LabelAt(24,Y+8,20,R.Get('label',''),350)
        else if Kind='input' then LabelAt(24,Y+8,16,R.Get('label',''),350,true)
        else LabelAt(24,Y+8,18,R.Get('label',''),350);
        if Kind='input' then
        begin
          if Focused and (EditAction<>'') then Value:=EditValue else Value:=R.Get('value','');
          if R.Get('secret',false) then Value:=StringOfChar('*',Length(Value));
          if Focused and EditSelectedAll and (EditAction<>'') then Rect(22,Y+35,350,29,0.60,0.055,0.22)
          else if Focused and (EditAction<>'') then
          begin
            Value:=EditorTail(Value,335);
            Rect(25+TextWidth(Value),Y+39,2,22,1,0.66,0.78);
          end;
          if (Value='') and (EditAction<>R.Get('action','')) then LabelAt(24,Y+40,18,'Clic para escribir',345,true)
          else LabelAt(24,Y+40,18,Value,345);
        end
        else if Kind='slider' then
        begin
          V:=R.Get('value',0.0); Rect(24,Y+44,290,8,0.28,0.26,0.29); Rect(24,Y+44,290*V/100,8,0.97,0.25,0.48);
          LabelAt(325,Y+36,16,IntToStr(Round(V))+'%',55);
        end
        else if R.Get('sub','')<>'' then LabelAt(24,Y+36,15,R.Get('sub',''),350,true);
        end;
      end;
      Inc(Y,RH);
    end;
    if Scroll>0 then Renderer.DrawTriangle(365,ContentTop-9,370,ContentTop-14,375,ContentTop-9,0,0.85,0.72,0.76,1);
    if Y>Height-98 then Renderer.DrawTriangle(365,Height-110,375,Height-110,370,Height-105,0,0.85,0.72,0.76,1);
    Rect(1,Height-94,399,94,0.126,0.125,0.14);
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
function RowAt(X,Y: single): integer;
var I,P,H: integer; A: TJSONArray;
begin
  Result:=-1; if not Assigned(View) or (X<16) or (X>=384) or (Y<ContentTop-6) or (Y>Height-98) then Exit;
  A:=View.Arrays['rows']; P:=ContentTop-Scroll;
  for I:=0 to A.Count-1 do begin H:=RowHeight(TJSONObject(A[I])); if (P>=ContentTop-6) and (P+H<=Height-98) and (Y>=P) and (Y<P+H-2) and ((TJSONObject(A[I]).Get('kind','')='song') or (Y<P+H-8)) then begin Result:=I; Exit; end; Inc(P,H); end;
end;
procedure SelectRow(I: integer; X: single=24; PointerAction: boolean=false; PointerY: single=0);
var R: TJSONObject; Kind: string; A: TJSONArray; Y,J: integer;
begin
  if not Assigned(View) then Exit;
  A:=View.Arrays['rows']; if (I<0) or (I>=A.Count) then Exit;
  CommitEdit; R:=TJSONObject(A[I]); Kind:=R.Get('kind','');
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
    if AddFocused or (R.Get('action','')='') then Emit(R.Get('add_action',''))
    else Emit(R.Get('action',''));
    Exit;
  end;
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
    if (ContentTop+Total-Scroll<ContentTop-6) or (ContentTop+Total-Scroll+RowHeight(TJSONObject(A[Focus]))>Height-98) then Scroll:=Total;
    R:=TJSONObject(A[Focus]); AddFocused:=Backwards and (R.Get('add_action','')<>'');
    if R.Get('kind','')='input' then
    begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); EditSelectedAll:=false; SDL_StartTextInput; end;
  end;
end;
function StagePointer(PX,PY: integer): boolean;
var W,I: integer; C: TJSONObject; A: TJSONArray;
begin
  W:=ScreenW-SideWidth; Result:=false;
  if Singing or (PX>=W) then Exit;
  if PanelCollapsed and Inside(Box(ScreenW-170,16,154,40),PX,PY) then Exit;
  Result:=true; CommitEdit; Focus:=-12; StageFocused:=true; PanelToggleFocused:=false;
  if ShowingResults then
  begin if Inside(ResultButton,PX,PY) then ResultsDismissed:=true; Exit; end;
  if not HasCarousel then
  begin
    if Inside(EmptyButton,PX,PY) then
    begin SetPanelCollapsed(false); StageFocused:=false; Emit('page:Buscar'); end;
    Exit;
  end;
  if Inside(HeroButton(W),PX,PY) or Inside(HeroArt(W),PX,PY) then
  begin Emit('carousel:enqueue'); Exit; end;
  C:=Carousel; A:=C.Arrays['songs'];
  if C.Get('has_previous',false) and Inside(ArrowBox(W,false),PX,PY) then Emit('carousel:previous')
  else if C.Get('has_next',false) and Inside(ArrowBox(W,true),PX,PY) then Emit('carousel:next')
  else for I:=0 to A.Count-1 do if Inside(SleeveBox(W,I),PX,PY) then
  begin Emit('carousel:select:'+TJSONObject(A[I]).Get('id','')); Exit; end;
end;
function ShellEvent(var Event: TSDL_Event): boolean;
var X,Y,P,I: integer; A: TJSONArray; R: TJSONObject; Clip: PAnsiChar; Key: cardinal;
begin
  Result:=false; if not ShellEnabled or not Started then Exit;
  if (Event.type_=SDL_WINDOWEVENT) and (Event.window.event=SDL_WINDOWEVENT_FOCUS_GAINED) then Display.SetCursor;
  if Event.type_=SDL_MOUSEMOTION then
  begin
    X:=Event.motion.x; Y:=Event.motion.y; PanelHover:=false; Hover:=-1;
    if PanelCollapsed then PanelHover:=(X>=ScreenW-170) and (X<=ScreenW-16) and (Y>=16) and (Y<=56)
    else if X>=ScreenW-SideWidth then
    begin
      X:=Round((X-ScreenW+SideWidth)*400/SideWidth); Y:=Round(Y*400/SideWidth);
      PanelHover:=(X>=338) and (X<=384) and (Y>=22) and (Y<=54);
      Hover:=RowAt(X,Y);
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
      else if (X>=12) and (X<392) and ((X-12) mod 96<92) and (Y>=68) and (Y<104) then
      begin
        CommitEdit; I:=(X-12) div 96; Focus:=I-10;
        case I of 0: Emit('page:Biblioteca'); 1: Emit('page:Buscar'); 2: Emit('page:Cola'); 3: Emit('page:Ajustes'); end;
      end else if (Y>=116) and (Y<152) and (((X>=16) and (X<196)) or ((X>=204) and (X<384))) and Singing then
      begin CommitEdit; if X<200 then Focus:=-6 else Focus:=-5; ActivateFocus; end
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
    else if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) or (Key=SDLK_PLUS) then
    begin
      if Assigned(View) and (Focus>=0) and (Focus<View.Arrays['rows'].Count) then
      begin R:=TJSONObject(View.Arrays['rows'][Focus]); if (R.Get('kind','')='song') and (R.Get('add_action','')<>'') and (Key<>SDLK_LEFT) then
        begin AddFocused:=true; Emit(R.Get('add_action','')); end
        else if (R.Get('kind','')='slider') and (Key<>SDLK_PLUS) then begin I:=5; if Key=SDLK_LEFT then I:=-5; Emit(R.Get('action',''),IntToStr(EnsureRange(R.Get('value',0)+I,0,100))); end; end;
    end
    else if (Key=SDLK_SPACE) and Singing then ScreenSing.Pause;
  end;
end;
end.
