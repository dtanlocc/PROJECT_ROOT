[Setup]
AppName=Reup Pro Professional
AppVersion=53.30
DefaultDirName={autopf}\Reup_Pro
PrivilegesRequired=admin
OutputBaseFilename=Reup_Pro_Setup
SetupIconFile=app\assets\icon.ico
OutputDir=.

; --- BẬT CHẾ ĐỘ NÉN TỐI ĐA CHUẨN INNO SETUP ---
Compression=lzma2/ultra64
SolidCompression=yes
LZMADictionarySize=131072
; -----------------------------------------------

[Files]
; 1. Nạp file requirements.txt vào bộ nhớ tạm
Source: "Reup_Video_Release\requirements.txt"; DestDir: "{tmp}"; Flags: dontcopy

; 2. Nạp các file cốt lõi NHƯNG BỎ QUA HOÀN TOÀN venv, bin và pycache (Để Tool cực nhẹ)
Source: "Reup_Video_Release\*"; DestDir: "{app}"; Excludes: "venv\*, bin\*, __pycache__\*, .git\*"; Flags: ignoreversion recursesubdirs createallsubdirs

; 3. Nạp Script kích hoạt PowerShell
Source: "activate.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Code]
type
  TMsg = record
    hwnd: HWND; message: UINT; wParam: Longint; lParam: Longint;
    time: DWORD; pt: TPoint; 
  end;

function PeekMessage(var lpMsg: TMsg; hWnd: HWND; wMsgFilterMin, wMsgFilterMax, wRemoveMsg: UINT): BOOL; external 'PeekMessageW@user32.dll stdcall';
function TranslateMessage(const lpMsg: TMsg): BOOL; external 'TranslateMessage@user32.dll stdcall';
function DispatchMessage(const lpMsg: TMsg): Longint; external 'DispatchMessageW@user32.dll stdcall';
function SendMessage(hWnd: HWND; Msg: Integer; wParam, lParam: Longint): Longint; external 'SendMessageW@user32.dll stdcall';

var
  LicensePage: TInputQueryWizardPage;
  InstallTypePage: TInputOptionWizardPage;
  ProgressPage: TWizardPage;
  ProgressBar: TNewProgressBar;
  LogMemo: TNewMemo;
  StatusLabel: TNewStaticText;
  IsRunning: Boolean;

procedure ProcessMessages;
var Msg: TMsg;
begin
  while PeekMessage(Msg, 0, 0, 0, 1) do begin
    TranslateMessage(Msg);
    DispatchMessage(Msg);
  end;
end;

procedure InitializeWizard;
begin
  InstallTypePage := CreateInputOptionPage(wpSelectDir, 'Cấu hình phần cứng', 
    'Chọn chế độ cài đặt phù hợp với máy của bạn.', 
    'Lưu ý: Chế độ GPU yêu cầu Card NVIDIA và đã cài Driver.', True, False);
  InstallTypePage.Add('Sử dụng GPU (Tốc độ xử lý nhanh - Yêu cầu NVIDIA)');
  InstallTypePage.Add('Sử dụng CPU (Tốc độ xử lý chậm - Dành cho máy không có Card rời)');
  InstallTypePage.Values[0] := True;

  LicensePage := CreateInputQueryPage(InstallTypePage.ID, 'Kích hoạt bản quyền', 
    'Vui lòng nhập Key.', '');
  LicensePage.Add('License Key:', False);

  ProgressPage := CreateCustomPage(LicensePage.ID, 'Tiến trình thiết lập', 'Đang cài đặt môi trường...');
  
  StatusLabel := TNewStaticText.Create(ProgressPage);
  StatusLabel.Parent := ProgressPage.Surface;
  StatusLabel.Caption := 'Đang khởi tạo...';
  
  ProgressBar := TNewProgressBar.Create(ProgressPage);
  ProgressBar.Parent := ProgressPage.Surface;
  ProgressBar.Top := StatusLabel.Top + StatusLabel.Height + 8;
  ProgressBar.Width := ProgressPage.SurfaceWidth;
  ProgressBar.Style := npbstMarquee;

  LogMemo := TNewMemo.Create(ProgressPage);
  LogMemo.Parent := ProgressPage.Surface;
  LogMemo.Top := ProgressBar.Top + ProgressBar.Height + 12;
  LogMemo.Width := ProgressPage.SurfaceWidth;
  LogMemo.Height := ProgressPage.SurfaceHeight - LogMemo.Top - 10;
  LogMemo.ReadOnly := True;
  LogMemo.ScrollBars := ssVertical;
  LogMemo.Color := clBlack;
  LogMemo.Font.Color := clLime;
  LogMemo.Font.Name := 'Consolas';
end;

procedure RunFlow;
var
  ResCode: Integer;
  LogF, StatusF, KeyStr, Path, Params, InstallType: String;
  CheckStr: AnsiString;
begin
  if IsRunning then Exit;
  IsRunning := True;

  KeyStr := Trim(LicensePage.Values[0]);
  Path := WizardDirValue; 
  
  if InstallTypePage.Values[0] then
    InstallType := 'GPU'
  else
    InstallType := 'CPU';

  LogF := Path + '\activation_debug.log';
  StatusF := Path + '\status.tmp';

  ForceDirectories(Path);
  ExtractTemporaryFile('activate.ps1');
  ExtractTemporaryFile('requirements.txt'); 
  CopyFile(ExpandConstant('{tmp}\requirements.txt'), Path + '\requirements.txt', False);

  WizardForm.NextButton.Enabled := False;
  WizardForm.BackButton.Enabled := False;

  Params := Format('-ExecutionPolicy Bypass -File "%s" "%s" "%s" "%s"', [ExpandConstant('{tmp}\activate.ps1'), KeyStr, Path, InstallType]);
  
  Exec('powershell.exe', Params, '', SW_HIDE, ewNoWait, ResCode);

  while not FileExists(StatusF) do begin
    if FileExists(LogF) then begin
      if CopyFile(LogF, LogF + '.read', False) then begin
        LogMemo.Lines.LoadFromFile(LogF + '.read');
        SendMessage(LogMemo.Handle, $0115, 7, 0); 
      end;
    end;
    ProcessMessages;
    Sleep(150);
  end;

  if FileExists(StatusF) then begin
    if LoadStringFromFile(StatusF, CheckStr) then begin
      if Pos('DONE_SUCCESS', String(CheckStr)) > 0 then begin
        StatusLabel.Caption := 'Cấu hình hoàn tất!';
        WizardForm.NextButton.Enabled := True;
      end else begin
        MsgBox('Kích hoạt thất bại. Vui lòng kiểm tra log.', mbError, MB_OK);
        WizardForm.Close;
      end;
    end;
  end;
  
  if FileExists(StatusF) then DeleteFile(StatusF);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = ProgressPage.ID then RunFlow;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = LicensePage.ID) and (Trim(LicensePage.Values[0]) = '') then begin
    MsgBox('Chưa nhập Key!', mbError, MB_OK);
    Result := False;
  end;
end;