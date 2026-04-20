import streamlit as st
import httpx
from datetime import datetime, timedelta
import uuid

st.set_page_config(page_title="Overlord Key Manager", page_icon="🔑", layout="centered")

st.title("🔑 Overlord License Key Manager")
st.markdown("### Quản lý bản quyền Supabase")

# ====================== CONFIG ======================
SUPABASE_URL = "https://gfihmymecoykcogqykbl.supabase.co"

# Nhập Service Role Key (bảo mật)
if "service_role" not in st.session_state:
    st.session_state.service_role = ""

service_role = st.text_input(
    "🔐 Supabase Service Role Key", 
    value=st.session_state.service_role,
    type="password",
    help="Dán Service Role Key vào đây"
)

if service_role:
    st.session_state.service_role = service_role

# ====================== FORM TẠO KEY ======================
st.subheader("Tạo License Key Mới")

col1, col2 = st.columns([3, 1])

with col1:
    key_input = st.text_input("License Key", placeholder="VIP-2026-ABC123XYZ", help="Nhập key bạn muốn tạo")

with col2:
    key_type = st.selectbox("Loại Key", ["Có thời hạn", "Vĩnh viễn"])

days = st.number_input("Thời hạn (ngày)", min_value=1, value=30, disabled=(key_type == "Vĩnh viễn"))

if st.button("🚀 Tạo Key", type="primary", use_container_width=True):
    if not service_role:
        st.error("❌ Vui lòng nhập Service Role Key")
    elif not key_input.strip():
        st.error("❌ Vui lòng nhập License Key")
    else:
        with st.spinner("Đang tạo key..."):
            expires_at = None if key_type == "Vĩnh viễn" else (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

            payload = {
                "key": key_input.strip(),
                "status": "active",
                "expires_at": expires_at,
                # hwid để trống → tự động lock khi user kích hoạt lần đầu
            }

            headers = {
                "apikey": service_role,
                "Authorization": f"Bearer {service_role}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }

            try:
                response = httpx.post(
                    f"{SUPABASE_URL}/rest/v1/licenses",
                    json=payload,
                    headers=headers,
                    timeout=10
                )

                if response.status_code in (200, 201):
                    st.success("✅ Tạo key thành công!")
                    st.balloons()
                    
                    st.info(f"**Key:** `{key_input.strip()}`")
                    st.info(f"**Loại:** {key_type}")
                    if expires_at:
                        st.info(f"**Hết hạn:** {expires_at[:10]}")
                else:
                    st.error(f"❌ Lỗi {response.status_code}")
                    st.code(response.text)
            except Exception as e:
                st.error(f"Lỗi kết nối: {e}")

# ====================== XEM DANH SÁCH KEY ======================
st.divider()
st.subheader("📋 Danh sách License Keys")

if service_role and st.button("🔄 Tải danh sách Key"):
    with st.spinner("Đang tải..."):
        headers = {
            "apikey": service_role,
            "Authorization": f"Bearer {service_role}"
        }
        try:
            r = httpx.get(f"{SUPABASE_URL}/rest/v1/licenses?select=*&order=created_at.desc", headers=headers)
            if r.status_code == 200:
                data = r.json()
                if data:
                    st.dataframe(data, use_container_width=True)
                else:
                    st.info("Chưa có key nào.")
            else:
                st.error("Không thể lấy danh sách")
        except:
            st.error("Lỗi kết nối")