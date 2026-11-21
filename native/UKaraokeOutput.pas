{ Identity of the OS default output used by SDL. Queried between performances on the UI thread. }
unit UKaraokeOutput;
{$mode objfpc}{$H+}
{$IFDEF DARWIN}{$linkframework CoreAudio}{$linkframework CoreFoundation}{$ENDIF}
interface
function SystemOutputID(const Driver: UTF8String): UTF8String;
function PreferShortDuplex(const Driver, Model, InputID, OutputID, Profile: UTF8String;
  Rate: Double; DefaultSplit, AutomaticLatency: Boolean): Boolean;
function KnownShortDuplex(const Driver: UTF8String; Rate: Double;
  DefaultSplit, AutomaticLatency: Boolean): Boolean;
implementation
uses SysUtils
  {$IFDEF DARWIN}, AudioHardware, AudioHardwareBase, CFBase, CFString{$ENDIF}
  {$IFDEF MSWINDOWS}, Windows, ActiveX{$ENDIF};
{$IFDEF DARWIN}
function ReadSysctl(Name: PAnsiChar; OldValue: Pointer; var Size: SizeUInt;
  NewValue: Pointer; NewSize: SizeUInt): LongInt; cdecl; external 'c' name 'sysctlbyname';

function MacHardwareModel: UTF8String;
var Buffer: array[0..127] of AnsiChar; Size: SizeUInt;
begin
  Result:=''; Size:=SizeOf(Buffer);
  if (ReadSysctl('hw.model',@Buffer[0],Size,nil,0)=0) and (Size>0) then
    Result:=UTF8String(PAnsiChar(@Buffer[0]));
end;

function CoreAudioDeviceID(Selector: AudioObjectPropertySelector): UTF8String;
var Address: AudioObjectPropertyAddress; Device: AudioObjectID; Bytes: UInt32;
    UID: CFStringRef; Text: array[0..1023] of AnsiChar;
begin
  Result:=''; Address.mScope:=kAudioObjectPropertyScopeGlobal; Address.mElement:=0;
  Address.mSelector:=Selector;
  Bytes:=SizeOf(Device); Device:=0;
  if (AudioObjectGetPropertyData(kAudioObjectSystemObject,Address,0,nil,Bytes,@Device)<>0) or (Device=0) then Exit;
  Address.mSelector:=kAudioDevicePropertyDeviceUID; Bytes:=SizeOf(UID); UID:=nil;
  if (AudioObjectGetPropertyData(Device,Address,0,nil,Bytes,@UID)<>0) or (UID=nil) then Exit;
  try
    if CFStringGetCString(UID,@Text[0],Length(Text),kCFStringEncodingUTF8) then Result:='coreaudio:'+UTF8String(PAnsiChar(@Text[0]));
  finally CFRelease(UID); end;
end;
{$ENDIF}
{$IFDEF MSWINDOWS}
type
  IMMDevice = interface(IUnknown)
    ['{D666063F-1587-4E43-81F1-B948E807363F}']
    function Activate(const IID: TGUID; Context: DWORD; Params: Pointer; out Obj: Pointer): HRESULT; stdcall;
    function OpenPropertyStore(Mode: DWORD; out Store: IUnknown): HRESULT; stdcall;
    function GetId(out ID: PWideChar): HRESULT; stdcall;
    function GetState(out State: DWORD): HRESULT; stdcall;
  end;
  IMMDeviceEnumerator = interface(IUnknown)
    ['{A95664D2-9614-4F35-A746-DE8DB63617E6}']
    function EnumAudioEndpoints(Flow: integer; Mask: DWORD; out Collection: IUnknown): HRESULT; stdcall;
    function GetDefaultAudioEndpoint(Flow,Role: integer; out Endpoint: IMMDevice): HRESULT; stdcall;
  end;
const MMEnumerator: TGUID = '{BCDE0395-E52F-467C-8E3D-C4579291692E}';
      EnumeratorIID: TGUID = '{A95664D2-9614-4F35-A746-DE8DB63617E6}';
function WasapiOutputID: UTF8String;
var Enumerate: IMMDeviceEnumerator; Endpoint: IMMDevice; ID: PWideChar; Init: HRESULT;
begin
  Result:=''; Init:=CoInitializeEx(nil,COINIT_MULTITHREADED);
  try
    if CoCreateInstance(MMEnumerator,nil,CLSCTX_INPROC_SERVER,EnumeratorIID,Enumerate)<>S_OK then Exit;
    { SDL 2 WASAPI opens the eRender/eConsole default. }
    if Enumerate.GetDefaultAudioEndpoint(0,0,Endpoint)<>S_OK then Exit;
    ID:=nil;
    if (Endpoint.GetId(ID)<>S_OK) or (ID=nil) then Exit;
    try Result:='wasapi:'+UTF8Encode(UnicodeString(ID)); finally CoTaskMemFree(ID); end;
  finally
    Endpoint:=nil; Enumerate:=nil;
    if Init>=0 then CoUninitialize;
  end;
end;
{$ENDIF}
function SystemOutputID(const Driver: UTF8String): UTF8String;
begin
  Result:='';
  {$IFDEF DARWIN} if SameText(Driver,'coreaudio') then Result:=CoreAudioDeviceID(kAudioHardwarePropertyDefaultOutputDevice); {$ENDIF}
  {$IFDEF MSWINDOWS} if SameText(Driver,'wasapi') then Result:=WasapiOutputID; {$ENDIF}
end;

function PreferShortDuplex(const Driver, Model, InputID, OutputID, Profile: UTF8String;
  Rate: Double; DefaultSplit, AutomaticLatency: Boolean): Boolean;
begin
  Result := (Driver='coreaudio') and DefaultSplit and AutomaticLatency and (Rate=48000)
    and (Model='Mac16,1') and (InputID='coreaudio:BuiltInMicrophoneDevice')
    and (OutputID='coreaudio:BuiltInSpeakerDevice') and ((Profile='') or (Profile='10ms-64'));
end;

function KnownShortDuplex(const Driver: UTF8String; Rate: Double;
  DefaultSplit, AutomaticLatency: Boolean): Boolean;
begin
  Result:=false;
  {$IFDEF DARWIN}
  if (Driver='coreaudio') and DefaultSplit and AutomaticLatency then
    Result:=PreferShortDuplex(Driver, MacHardwareModel,
      CoreAudioDeviceID(kAudioHardwarePropertyDefaultInputDevice),
      CoreAudioDeviceID(kAudioHardwarePropertyDefaultOutputDevice),
      GetEnvironmentVariable('KARAOKE_DUPLEX_PROFILE'), Rate, DefaultSplit, AutomaticLatency);
  {$ENDIF}
end;
end.
