# app/core/security.py
import subprocess
import hashlib
import sys

def get_hwid():
    """Lấy Hardware ID duy nhất của máy"""
    try:
        # Lấy UUID Mainboard
        cmd = "wmic csproduct get uuid"
        uuid = subprocess.check_output(cmd, shell=True).decode().split('\n')[1].strip()
        # Lấy Serial Ổ cứng
        cmd2 = "wmic diskdrive get serialnumber"
        hdd = subprocess.check_output(cmd2, shell=True).decode().split('\n')[1].strip()
        
        raw = f"{uuid}-{hdd}-SuperReupAI_Secret_Salt" 
        return hashlib.sha256(raw.encode()).hexdigest().upper()
    except:
        return "UNKNOWN-HWID"

def check_integrity():
    """Kiểm tra xem file có bị hack/debug không (Placeholder)"""
    # Sau này sẽ thêm logic check hash file .pyd tại đây
    pass