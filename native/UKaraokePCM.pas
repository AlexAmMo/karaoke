{ Stateful PCM conversion used by one playback stream. GPL-3.0-only. }
unit UKaraokePCM;
{$mode delphi}{$H+}
interface
uses SDL2;
type
  TKaraokePCM = class
    private
      Handle: Pointer;
      EndOfInput: Boolean;
    public
      constructor Create(InputFormat: Word; InputChannels: Byte; InputRate: Integer;
                         OutputFormat: Word; OutputChannels: Byte; OutputRate: Integer);
      destructor Destroy; override;
      function Ready: Boolean;
      function Push(Data: Pointer; Bytes: Integer): Boolean;
      function Finish: Boolean;
      procedure Clear;
      function Available: Integer;
      function Read(Data: Pointer; Capacity: Integer): Integer;
      property Finished: Boolean read EndOfInput;
  end;
implementation
{ The SDL2 headers shipped by Deluxe predate SDL 2.0.7. Both packaged SDL2
  backends export the streaming API. A persistent stream retains fractional
  phase across chunks and reports how many complete output bytes can be read. }
function SDL_NewAudioStream(SrcFormat: Word; SrcChannels: Byte; SrcRate: Integer;
  DstFormat: Word; DstChannels: Byte; DstRate: Integer): Pointer; cdecl; external SDL_LibName;
procedure SDL_FreeAudioStream(Stream: Pointer); cdecl; external SDL_LibName;
function SDL_AudioStreamPut(Stream, Data: Pointer; Bytes: Integer): Integer; cdecl; external SDL_LibName;
function SDL_AudioStreamFlush(Stream: Pointer): Integer; cdecl; external SDL_LibName;
procedure SDL_AudioStreamClear(Stream: Pointer); cdecl; external SDL_LibName;
function SDL_AudioStreamAvailable(Stream: Pointer): Integer; cdecl; external SDL_LibName;
function SDL_AudioStreamGet(Stream, Data: Pointer; Bytes: Integer): Integer; cdecl; external SDL_LibName;

constructor TKaraokePCM.Create(InputFormat: Word; InputChannels: Byte; InputRate: Integer;
                               OutputFormat: Word; OutputChannels: Byte; OutputRate: Integer);
begin
  inherited Create;
  Handle := SDL_NewAudioStream(InputFormat, InputChannels, InputRate, OutputFormat, OutputChannels, OutputRate);
end;

destructor TKaraokePCM.Destroy;
begin
  if Handle <> nil then SDL_FreeAudioStream(Handle);
  inherited;
end;

function TKaraokePCM.Ready: Boolean;
begin
  Result := Handle <> nil;
end;

function TKaraokePCM.Push(Data: Pointer; Bytes: Integer): Boolean;
begin
  Result := SDL_AudioStreamPut(Handle, Data, Bytes) = 0;
end;

function TKaraokePCM.Finish: Boolean;
begin
  Result := EndOfInput or (SDL_AudioStreamFlush(Handle) = 0);
  if Result then EndOfInput := true;
end;

procedure TKaraokePCM.Clear;
begin
  SDL_AudioStreamClear(Handle);
  EndOfInput := false;
end;

function TKaraokePCM.Available: Integer;
begin
  Result := SDL_AudioStreamAvailable(Handle);
end;

function TKaraokePCM.Read(Data: Pointer; Capacity: Integer): Integer;
begin
  Result := SDL_AudioStreamGet(Handle, Data, Capacity);
end;
end.
