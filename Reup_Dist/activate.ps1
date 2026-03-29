param([string]$LicenseKey, [string]$InstallDir, [string]$InstallType)

$SupabaseUrl = "https://gfihmymecoykcogqykbl.supabase.co"
$AnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdmaWhteW1lY295a2NvZ3F5a2JsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA5NjU4MTMsImV4cCI6MjA4NjU0MTgxM30.SWsdEyLWkOu2tKZS3ZFKk2riCR5uxubXbFvz0a12e_Q"
$LogFile = Join-Path $InstallDir "activation_debug.log"
$StatusFile = Join-Path $InstallDir "status.tmp"

if (Test-Path $LogFile) { Remove-Item $LogFile }

function Write-Log($Msg) {
    if (![string]::IsNullOrWhiteSpace($Msg)) {
        $Timestamp = Get-Date -Format "HH:mm:ss"
        $Line = "[$Timestamp] $Msg`r`n"
        
        $RetryCount = 0
        while ($RetryCount -lt 10) {
            try {
                $fs = [System.IO.File]::Open($LogFile, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
                $bytes = [System.Text.Encoding]::UTF8.GetBytes($Line)
                $fs.Write($bytes, 0, $bytes.Length)
                $fs.Close()
                break
            } catch {
                $RetryCount++
                Start-Sleep -Milliseconds 50
            }
        }
    }
}

try {
    if (!(Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force }
    Write-Log "--- Bat dau kich hoat Key: $LicenseKey ---"

    # 1. TÍNH HWID
    $uuid = (Get-WmiObject -Class Win32_ComputerSystemProduct).UUID.Trim()
    $salt = "OVERLORD_" + $uuid + "_SALT"
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    $hwidBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($salt))
    $hwid = ([System.BitConverter]::ToString($hwidBytes).Replace("-", "").ToUpper().Substring(0, 24))
    Write-Log "HWID tinh duoc: $hwid"

    # 2. KHÓA HWID LÊN SERVER VÀ KIỂM TRA
    $Headers = @{ "apikey" = $AnonKey; "Authorization" = "Bearer $AnonKey"; "Content-Type" = "application/json"; "Prefer" = "return=representation" }
    $ApiUrl = "$SupabaseUrl/rest/v1/licenses?key=eq.$LicenseKey"
    
    Write-Log "Dang goi PATCH de khoa HWID..."
    $PatchRes = Invoke-RestMethod -Uri $ApiUrl -Method Patch -Body (@{ hwid = $hwid } | ConvertTo-Json) -Headers $Headers
    
    if ($null -eq $PatchRes -or $PatchRes.Count -eq 0) {
        Write-Log "LOI: Key khong ton tai hoac da bi khoa cho HWID khac."
        "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
        exit 1
    }

    # 3. TẠO FILE CHỨNG CHỈ LOCAL (system.lic)
    $rawSig = "||$LicenseKey||<<SECURE>>||$hwid||"
    $sha512 = [System.Security.Cryptography.SHA512]::Create()
    $hashBytes = $sha512.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($rawSig))
    $finalHash = [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()
    $LicData = @{ key = $LicenseKey; hash = $finalHash } | ConvertTo-Json -Compress
    
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText("$InstallDir\system.lic", $LicData, $utf8NoBom)
    
    Write-Log "Da tao xong file system.lic"

    # =========================================================================
    # TẢI THƯ VIỆN DLL (GPU) TỪ DIRECT LINK (TỐC ĐỘ CAO - KHÔNG LỖI)
    # =========================================================================
    if ($InstallType -eq "GPU") {
        Write-Log "Dang tai thu vien loi GPU (bin.zip) tu may chu... Vui long doi khoang 1-3 phut tuy mang."
        
        # ---> DÁN DIRECT LINK CỦA BẠN VÀO ĐÂY (VD: Link Dropbox có đuôi ?dl=1) <---
        $DirectUrl = "https://www.dropbox.com/scl/fi/d6yfqrz5cfmxty6cuusot/bin.zip?rlkey=sn6k0xtzgwhriibk05g2ucbs7&st=cbyby6oy&dl=1"
        
        $ZipPath = Join-Path $InstallDir "bin.zip"
        $BinDir = Join-Path $InstallDir "bin"

        try {
            # Ép dùng giao thức TLS 1.2 bảo mật (chống lỗi kết nối bị ngắt)
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            
            # Tải file trực tiếp (Rất ổn định, không bị dính HTML)
            Invoke-WebRequest -Uri $DirectUrl -OutFile $ZipPath -UseBasicParsing
            
            # Kiểm tra xem file tải về có dung lượng đàng hoàng không (Lớn hơn 1MB)
            $ZipSize = (Get-Item $ZipPath).Length
            if ($ZipSize -lt 1000000) {
                throw "File tai ve qua nho ($ZipSize bytes). Link tai bi loi hoac bi chan!"
            }

            Write-Log "Da tai xong file zip. Dang giai nen vao thu muc he thong..."
            if (!(Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
            
            # Giải nén
            Expand-Archive -Path $ZipPath -DestinationPath $BinDir -Force
            
            # Dọn dẹp
            Remove-Item $ZipPath -Force
            Write-Log "Giai nen thu vien GPU thanh cong!"
            
        } catch {
            Write-Log "LOI NGHIEM TRONG: Khong the tai hoac giai nen. Chi tiet: $($_.Exception.Message)"
            "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
            exit 1
        }
    } else {
        Write-Log "Che do CPU: Bo qua buoc tai thu vien GPU nang."
    }
    # =========================================================================

    $AssetName = "setup_cpu.bat"
    if ($InstallType -eq "GPU") {
        $AssetName = "setup_gpu.bat"
    }

    # 4. RÚT MÃ SETUP.BAT TỪ RPC
    Write-Log "Che do lua chon: $InstallType. Dang tai file: $AssetName"
    Write-Log "Dang goi RPC de rut file .bat bao mat..."
    $RpcUrl = "$SupabaseUrl/rest/v1/rpc/get_secure_payload"
    $RpcBody = @{ p_key = $LicenseKey; p_hwid = $hwid; p_asset = $AssetName } | ConvertTo-Json
    
    $BatContent = Invoke-RestMethod -Uri $RpcUrl -Method Post -Body $RpcBody -Headers $Headers
    
    if ([string]::IsNullOrWhiteSpace($BatContent)) {
        throw "Khong the tai noi dung file setup tu server (Asset: $AssetName)"
    }

    # 5. LƯU VÀ CHẠY
    $BatPath = Join-Path $InstallDir "setup_venv.bat"
    Set-Content -Path $BatPath -Value $BatContent -Encoding Ascii
    Write-Log "Da luu file .bat. Dang khoi chay cai dat venv cho che do $InstallType..."
    
    Set-Location -Path $InstallDir
    & cmd.exe /c "`"$BatPath`"" 2>&1 | ForEach-Object {
        Write-Log $_
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Log "LOI: File .bat tra ve ma loi $LASTEXITCODE"
        "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
        exit 1
    }

    Write-Log "--- KICH HOAT THANH CONG ---"
    "DONE_SUCCESS" | Out-File -FilePath $StatusFile -Encoding UTF8
    exit 0

} catch {
    Write-Log "LOI NGHIEM TRONG: $($_.Exception.Message)"
    "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
    exit 1
}