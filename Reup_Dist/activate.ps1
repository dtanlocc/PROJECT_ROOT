param([string]$LicenseKey, [string]$InstallDir, [string]$InstallType)

# ==================== EDGE FUNCTION ====================
$EdgeFunctionUrl = "https://gfihmymecoykcogqykbl.supabase.co/functions/v1/activate-license"

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
    
    Write-Log "--- Bat dau Cai dat Reu_Video_Pro.exe---"

    # ==============================================================================
    # 2. GỌI EDGE FUNCTION
    # ==============================================================================
    Write-Log "Dang goi Edge Function de kich hoat..."

    $Body = @{
        p_key          = $LicenseKey
        p_hwid         = $hwid
        p_install_type = $InstallType
    } | ConvertTo-Json

    $Response = Invoke-RestMethod -Uri $EdgeFunctionUrl `
                                  -Method Post `
                                  -Body $Body `
                                  -ContentType "application/json" `
                                  -TimeoutSec 60

    # Lấy dữ liệu từ Edge Function (Hỗ trợ cả trả về JSON .data hoặc .bat_content)
    $BatContent = if ($null -ne $Response.bat_content) { $Response.bat_content } else { $Response.data }
    $ExpiresAt = if ($null -ne $Response.expires) { $Response.expires } else { "null" }

    if ([string]::IsNullOrWhiteSpace($BatContent)) {
        Write-Log "LOI: Khong the lay noi dung file setup tu server"
        "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
        exit 1
    }

    # ==============================================================================
    # 3. TẢI GPU (Giữ nguyên của bạn)
    # ==============================================================================
    if ($InstallType -eq "GPU") {
        Write-Log "Dang tai thu vien loi GPU (bin.zip)..."
        $DirectUrl = "https://www.dropbox.com/scl/fi/3wimwokqsl759lx9poevd/bin.zip?rlkey=d1airj4cnjtj8ce7hs1dkwavz&st=czqb8grd&dl=1"
        $ZipPath = Join-Path $InstallDir "bin.zip"
        $BinDir = Join-Path $InstallDir "bin"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $DirectUrl -OutFile $ZipPath -UseBasicParsing
            $ZipSize = (Get-Item $ZipPath).Length
            if ($ZipSize -lt 1000000) { throw "File tai ve qua nho ($ZipSize bytes)" }
            Write-Log "Da tai xong file zip. Dang giai nen..."
            if (!(Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
            Expand-Archive -Path $ZipPath -DestinationPath $BinDir -Force
            Remove-Item $ZipPath -Force
            Write-Log "Giai nen thu vien GPU thanh cong!"
        } catch {
            Write-Log "LOI NGHIEM TRONG: $($_.Exception.Message)"
            "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
            exit 1
        }
    } else {
        Write-Log "Che do CPU: Bo qua buoc tai GPU"
    }

    # ==============================================================================
    # 4. LƯU VÀ CHẠY .bat TẠO VENV
    # ==============================================================================
    $BatPath = Join-Path $InstallDir "setup_venv.bat"
    Set-Content -Path $BatPath -Value $BatContent -Encoding Ascii
    Write-Log "Da luu file .bat. Dang khoi chay cai dat venv..."

    Set-Location -Path $InstallDir
    & cmd.exe /c "`"$BatPath`"" 2>&1 | ForEach-Object { Write-Log $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "LOI: File .bat tra ve ma loi $LASTEXITCODE"
        "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
        exit 1
    }


    Write-Log "--- KICH HOAT BANG CACH NHAP KEY VAO GUI REUP_VIDEO_PRO.EXE ---"
    "DONE_SUCCESS" | Out-File -FilePath $StatusFile -Encoding UTF8
    exit 0

} catch {
    Write-Log "LOI NGHIEM TRONG: $($_.Exception.Message)"
    "DONE_FAIL" | Out-File -FilePath $StatusFile -Encoding UTF8
    exit 1
}