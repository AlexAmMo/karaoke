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
  Sequence: integer = 0;
  SynthPosition: int64 = 0;
  SynthTick: cardinal;
  Gains: array[0..1] of single;
  Hover: integer = -1;
  PendingForget: TStringList;
  TestingInput: boolean = false;
  LastMouseX, LastMouseY, MouseClicks: integer;
  LastAction: string;

function Root: string;
begin Result:=GetEnvironmentVariable('KARAOKE_IPC'); end;
function ShellEnabled: boolean;
begin Result:=Root<>''; end;
function ShellSynthetic: boolean;
begin Result:=ShellEnabled and (GetEnvironmentVariable('KARAOKE_TEST_INPUT')='1'); end;
function Singing: boolean;
begin Result:=Assigned(ScreenSing) and Assigned(Display.CurrentScreen) and (Display.CurrentScreen^=ScreenSing); end;
function SideWidth: integer;
begin Result:=Round(EnsureRange(ScreenW*0.34,340.0,440.0)); end;
function Height: single;
begin Result:=ScreenH*400/SideWidth; end;
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
      Token:=J.Get('token',''); ErrorText:='';
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
    Frequency: double; Name: string;
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
      J:=ReadJSON(Root+'/view.json');
      if J.Get('page','')<>Page then
      begin Page:=J.Get('page',''); Focus:=-1; EditAction:=''; Scroll:=0; SDL_StopTextInput; end;
      View.Free; View:=J;
      if Focus>=View.Arrays['rows'].Count then begin Focus:=-1; EditAction:=''; SDL_StopTextInput; end;
    except end;
  end;
  if NowTick-LastStatus>200 then
  begin
    LastStatus:=NowTick; J:=TJSONObject.Create;
    if TestingInput then for I:=0 to 1 do AudioInputProcessor.Sound[I].AnalyzeBuffer;
    try
      if Singing then J.Add('state','singing') else J.Add('state','idle');
      J.Add('mouse_x',LastMouseX); J.Add('mouse_y',LastMouseY); J.Add('mouse_clicks',MouseClicks); J.Add('width',ScreenW); J.Add('height',ScreenH); J.Add('last_action',LastAction);
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
  SetFontFamily(0); SetFontStyle(ftRegular); SetFontItalic(false); SetFontSize(Size);
  if Muted then SetFontColor(0.70,0.74,0.77,1) else SetFontColor(0.95,0.95,0.93,1);
  T:=S;
  if TextWidth(T)>Width then
  begin
    while (Length(T)>0) and (TextWidth(T+'...')>Width) do TrimLast(T);
    T:=T+'...';
  end;
  SetFontPos(X,Y); PrintText(T);
end;
procedure Rect(X,Y,W,H: single; R,G,B: single);
begin Renderer.DrawQuad(X,Y,0,W,H,R,G,B,1); end;
function RowHeight(Row: TJSONObject): integer;
begin if Row.Get('kind','')='input' then Result:=82 else if Row.Get('kind','')='slider' then Result:=74 else if Row.Get('sub','')<>'' then Result:=72 else Result:=48; end;
procedure ShellDraw;
var I,Y,RH,W: integer; A: TJSONArray; R: TJSONObject; Kind,Value,Msg: string; Focused: boolean; V: double;
begin
  if not ShellEnabled or not Started then Exit;
  W:=ScreenW-SideWidth;
  if not Singing then
  begin
    Renderer.SetViewPort(0,0,W,ScreenH); Renderer.SetOrthographicProjection(0,W,ScreenH,0,-1,100); Renderer.DepthTest:=false;
    Rect(0,0,W,ScreenH,0.045,0.054,0.061);
    LabelAt(48,48,28,'Karaoke',W-96);
    if Token='' then
    begin
      LabelAt(48,ScreenH*0.35,36,'Una canción más.',W-96);
      LabelAt(48,ScreenH*0.35+62,22,'Elige tu repertorio en el lateral.',W-96,true);
      LabelAt(48,ScreenH*0.35+102,20,'La letra, las notas y tu afinación aparecerán aquí.',W-96,true);
    end else
    begin
      LabelAt(48,ScreenH*0.28,34,'Tu interpretación',W-96);
      if Assigned(CurrentSong) then LabelAt(48,ScreenH*0.28+56,24,CurrentSong.Title,W-96,true);
      for I:=0 to Min(1,High(Player)) do
      begin
        LabelAt(48,ScreenH*0.28+124+I*70,24,Player[I].Name,W-240);
        LabelAt(W-190,ScreenH*0.28+124+I*70,30,IntToStr(Player[I].ScoreTotalInt),150);
      end;
    end;
    if ShellSynthetic then LabelAt(48,ScreenH-72,18,'PRUEBA: entrada sintética, sin micrófono real',W-96,true)
    else LabelAt(48,ScreenH-72,18,'Prepara los micrófonos en Ajustes antes de cantar.',W-96,true);
  end;
  Renderer.SetViewPort(W,0,SideWidth,ScreenH); Renderer.SetOrthographicProjection(0,400,Height,0,-1,100); Renderer.DepthTest:=false;
  Rect(0,0,400,Height,0.085,0.10,0.11); Rect(0,0,1,Height,0.22,0.25,0.27);
  LabelAt(22,22,25,'Tu sesión',240);
  if Assigned(View) then LabelAt(290,29,16,IntToStr(View.Get('queue_count',0))+' turnos',90,true);
  for I:=0 to 3 do
  begin
    case I of 0: Value:='Biblioteca'; 1: Value:='Buscar'; 2: Value:='Cola'; 3: Value:='Ajustes'; end;
    if Page=Value then Rect(12+I*96,68,92,36,0.20,0.29,0.28);
    LabelAt(19+I*96,78,16,Value,86);
  end;
  if Singing then
  begin
    Rect(16,116,180,36,0.18,0.22,0.24); LabelAt(30,126,16,'Pausar / continuar',155);
    Rect(204,116,180,36,0.18,0.22,0.24); LabelAt(220,126,16,'Terminar canción',150);
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
        if Focused then Rect(13,Y-3,374,RH-2,0.53,0.75,0.66);
        if (Kind='button') or (Kind='input') or Focused then
        begin
          if Hover=I then Rect(16,Y,368,RH-8,0.21,0.26,0.27)
          else Rect(16,Y,368,RH-8,0.13,0.16,0.18);
        end;
        LabelAt(24,Y+8,18,R.Get('label',''),350);
        if Kind='input' then
        begin
          if Focused and (EditAction<>'') then Value:=EditValue else Value:=R.Get('value','');
          if R.Get('secret',false) then Value:=StringOfChar('*',Length(Value));
          if Focused then Value:=Value+'|';
          if Value='' then Value:='Clic para escribir';
          LabelAt(24,Y+40,18,Value,345,true);
        end
        else if Kind='slider' then
        begin
          V:=R.Get('value',0.0); Rect(24,Y+44,290,8,0.27,0.31,0.32); Rect(24,Y+44,290*V/100,8,0.53,0.75,0.66);
          LabelAt(325,Y+36,16,IntToStr(Round(V))+'%',55);
        end
        else if R.Get('sub','')<>'' then LabelAt(24,Y+36,15,R.Get('sub',''),350,true);
      end;
      Inc(Y,RH);
    end;
    if Scroll>0 then LabelAt(365,155,14,'^',20,true);
    if Y>Height-98 then LabelAt(365,Height-110,14,'v',20,true);
    Rect(1,Height-94,399,94,0.10,0.13,0.14);
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
  SDL_StopTextInput;
end;
function RowAt(Y: single): integer;
var I,P,H: integer; A: TJSONArray;
begin
  Result:=-1; if not Assigned(View) or (Y<168) or (Y>Height-98) then Exit;
  A:=View.Arrays['rows']; P:=174-Scroll;
  for I:=0 to A.Count-1 do begin H:=RowHeight(TJSONObject(A[I])); if (P>=168) and (P+H<=Height-98) and (Y>=P) and (Y<P+H) then begin Result:=I; Exit; end; Inc(P,H); end;
end;
procedure SelectRow(I: integer; X: single=24);
var R: TJSONObject; Kind: string; A: TJSONArray;
begin
  if not Assigned(View) then Exit;
  A:=View.Arrays['rows']; if (I<0) or (I>=A.Count) then Exit;
  CommitEdit; Focus:=I; R:=TJSONObject(A[I]); Kind:=R.Get('kind','');
  if Kind='input' then
  begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); SDL_StartTextInput; end
  else if Kind='button' then Emit(R.Get('action',''))
  else if Kind='slider' then Emit(R.Get('action',''),IntToStr(Round(EnsureRange((X-24)/290*100,0.0,100.0))));
end;
function ShellEvent(var Event: TSDL_Event): boolean;
var X,Y,P,I,Total: integer; A: TJSONArray; R: TJSONObject; Clip: PAnsiChar; Key: cardinal;
begin
  Result:=false; if not ShellEnabled or not Started then Exit;
  if Event.type_=SDL_MOUSEMOTION then
  begin X:=Event.motion.x; Y:=Round(Event.motion.y*400/SideWidth); if X>=ScreenW-SideWidth then Hover:=RowAt(Y) else Hover:=-1; end;
  if Event.type_=SDL_MOUSEBUTTONDOWN then
  begin
    LastMouseX:=Event.button.x; LastMouseY:=Event.button.y; Inc(MouseClicks);
    X:=Event.button.x; Y:=Round(Event.button.y*400/SideWidth);
    if X>=ScreenW-SideWidth then
    begin
      Result:=true; X:=Round((X-ScreenW+SideWidth)*400/SideWidth);
      if (Y>=68) and (Y<=108) then
      begin
        CommitEdit; Focus:=-1; I:=(X-12) div 96;
        case I of 0: Emit('page:Biblioteca'); 1: Emit('page:Buscar'); 2: Emit('page:Cola'); 3: Emit('page:Ajustes'); end;
      end else if (Y>=116) and (Y<=152) and Singing then begin if X<200 then Emit('pause') else Emit('end'); end
      else SelectRow(RowAt(Y),X);
    end else begin CommitEdit; Focus:=-1; Result:=true; end;
  end;
  if Event.type_=SDL_MOUSEWHEEL then
  begin
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
  if (Event.type_=SDL_TEXTINPUT) and (EditAction<>'') then
  begin if Length(EditValue)<4096 then EditValue:=EditValue+UTF8String(PAnsiChar(@Event.text.text[0])); Result:=true; end;
  if (Event.type_=SDL_KEYDOWN) or (Event.type_=SDL_KEYUP) then
  begin
    Result:=true; if Event.type_=SDL_KEYUP then Exit;
    Key:=Event.key.keysym.sym;
    if (Event.key.keysym._mod and (KMOD_CTRL or KMOD_GUI))<>0 then
    begin
      if Key=SDLK_q then begin Display.NextScreenWithCheck:=nil; Display.CheckOK:=true; Exit; end;
      if (Key>=SDLK_1) and (Key<=SDLK_4) then
      begin
        CommitEdit; Focus:=-1;
        case Key of SDLK_1: Emit('page:Biblioteca'); SDLK_2: Emit('page:Buscar'); SDLK_3: Emit('page:Cola'); SDLK_4: Emit('page:Ajustes'); end;
        Exit;
      end;
      if (Key=SDLK_v) and (EditAction<>'') then
      begin Clip:=SDL_GetClipboardText; if Clip<>nil then begin EditValue:=Copy(EditValue+UTF8String(Clip),1,4096); SDL_free(Clip); end; end;
      if (Key=SDLK_a) and (EditAction<>'') then EditValue:='';
      Exit;
    end;
    if Key=SDLK_TAB then
    begin
      CommitEdit;
      if Assigned(View) then
      begin
        A:=View.Arrays['rows']; if A.Count=0 then begin Focus:=-1; Exit; end; P:=0;
        repeat Inc(P); Inc(Focus); if Focus>=A.Count then Focus:=0;
        until (TJSONObject(A[Focus]).Get('kind','')<>'text') or (P>=A.Count);
        if TJSONObject(A[Focus]).Get('kind','')='text' then begin Focus:=-1; Exit; end;
        Total:=0; for I:=0 to Focus-1 do Inc(Total,RowHeight(TJSONObject(A[I])));
        if (174+Total-Scroll<168) or (174+Total-Scroll+RowHeight(TJSONObject(A[Focus]))>Height-98) then Scroll:=Total;
        R:=TJSONObject(A[Focus]); if R.Get('kind','')='input' then begin EditAction:=R.Get('action',''); EditValue:=R.Get('value',''); SDL_StartTextInput; end;
      end;
    end
    else if EditAction<>'' then
    begin
      if Key=SDLK_BACKSPACE then TrimLast(EditValue);
      if Key=SDLK_RETURN then CommitEdit;
      if Key=SDLK_ESCAPE then begin EditAction:=''; EditValue:=''; Focus:=-1; SDL_StopTextInput; end;
    end
    else if (Key=SDLK_RETURN) and (Focus>=0) then SelectRow(Focus)
    else if (Key=SDLK_LEFT) or (Key=SDLK_RIGHT) then
    begin
      if Assigned(View) and (Focus>=0) and (Focus<View.Arrays['rows'].Count) then
      begin R:=TJSONObject(View.Arrays['rows'][Focus]); if R.Get('kind','')='slider' then begin I:=5; if Key=SDLK_LEFT then I:=-5; Emit(R.Get('action',''),IntToStr(EnsureRange(R.Get('value',0)+I,0,100))); end; end;
    end
    else if (Key=SDLK_SPACE) and Singing then ScreenSing.Pause;
  end;
end;
end.
