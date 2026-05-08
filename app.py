import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import requests

# ==========================================
# 1. DATABASE SETUP & INITIALIZATION
# ==========================================
DB_NAME = "football_engine.db"

def get_connection():
    """Membuat koneksi ke database SQLite."""
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    """Inisialisasi tabel jika belum ada."""
    conn = get_connection()
    c = conn.cursor()
    
    # Tabel Users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # Tabel User Settings
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            openrouter_api_key TEXT,
            preferred_model TEXT DEFAULT 'gpt-4o',
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # Tabel Main Data (Data CRUD Sepak Bola)
    c.execute('''
        CREATE TABLE IF NOT EXISTS main_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            stats_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    
    # Tabel AI Analysis History
    c.execute('''
        CREATE TABLE IF NOT EXISTS ai_analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            match_id INTEGER,
            analysis_type TEXT,
            insight_output TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(match_id) REFERENCES main_data(id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. LOGIC FUNCTIONS (AUTH, CRUD, AI)
# ==========================================
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def register_user(username, password):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hash_password(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False 
    finally:
        conn.close()

def login_user(username, password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE username=? AND password=?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

def get_user_settings(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT openrouter_api_key, preferred_model FROM user_settings WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res if res else ("", "gpt-4o")

def save_user_settings(user_id, api_key, model):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM user_settings WHERE user_id=?", (user_id,))
    if c.fetchone():
        c.execute("UPDATE user_settings SET openrouter_api_key=?, preferred_model=? WHERE user_id=?", (api_key, model, user_id))
    else:
        c.execute("INSERT INTO user_settings (user_id, openrouter_api_key, preferred_model) VALUES (?, ?, ?)", (user_id, api_key, model))
    conn.commit()
    conn.close()

def add_match(user_id, match_date, home_team, away_team, stats_json):
    conn = get_connection()
    c = conn.cursor()
    c.execute('INSERT INTO main_data (user_id, match_date, home_team, away_team, stats_json) VALUES (?, ?, ?, ?, ?)', 
              (user_id, str(match_date), home_team, away_team, stats_json))
    conn.commit()
    conn.close()

def get_matches(user_id):
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, match_date, home_team, away_team, stats_json FROM main_data WHERE user_id=? ORDER BY id DESC", conn, params=(user_id,))
    conn.close()
    return df

def delete_match(match_id, user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM main_data WHERE id=? AND user_id=?", (match_id, user_id))
    conn.commit()
    conn.close()

def delete_all_matches(user_id):
    """Menghapus SEMUA data pertandingan beserta riwayat analisanya untuk user ini."""
    conn = get_connection()
    c = conn.cursor()
    # Hapus riwayat AI dulu agar tidak ada data yatim (orphaned data) karena relasi Foreign Key
    c.execute("DELETE FROM ai_analysis_history WHERE user_id=?", (user_id,))
    # Hapus data utama
    c.execute("DELETE FROM main_data WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_match_history(user_id, team1, team2, current_match_id):
    conn = get_connection()
    query = """
        SELECT match_date, home_team, away_team, stats_json FROM main_data 
        WHERE user_id = ? AND id != ? AND (home_team = ? OR away_team = ? OR home_team = ? OR away_team = ?)
        ORDER BY match_date DESC LIMIT 10
    """
    df_history = pd.read_sql_query(query, conn, params=(user_id, current_match_id, team1, team1, team2, team2))
    conn.close()
    return df_history

def add_ai_report(user_id, match_id, analysis_type, insight_output):
    conn = get_connection()
    c = conn.cursor()
    # Mengamankan tipe data (konversi paksa ke integer dan string python standar)
    c.execute('INSERT INTO ai_analysis_history (user_id, match_id, analysis_type, insight_output) VALUES (?, ?, ?, ?)', 
              (int(user_id), int(match_id), str(analysis_type), str(insight_output)))
    conn.commit()
    conn.close()

def get_ai_reports(user_id):
    conn = get_connection()
    query = '''
        SELECT a.id, m.match_date, m.home_team, m.away_team, a.analysis_type, a.insight_output, a.created_at
        FROM ai_analysis_history a
        JOIN main_data m ON a.match_id = m.id
        WHERE a.user_id=? ORDER BY a.id DESC
    '''
    df = pd.read_sql_query(query, conn, params=(user_id,))
    conn.close()
    return df

def call_openrouter_api(api_key, model, prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=40)
        response.raise_for_status() 
        # Return Tuple (True/False, Pesan) agar lebih aman
        return True, response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return False, f"Error System API: {str(e)}"

# ==========================================
# 3. UI & ROUTING
# ==========================================
st.set_page_config(page_title="Football Engine", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    tab_auth_l, tab_auth_r = st.sidebar.tabs(["Login", "Register"])
    with tab_auth_r:
        st.title("Register Akun")
        with st.form("reg_f"):
            u, p = st.text_input("Username"), st.text_input("Password", type="password")
            if st.form_submit_button("Daftar"):
                if register_user(u, p): st.success("Sukses! Silakan Login.")
                else: st.error("Username sudah ada.")
    with tab_auth_l:
        st.title("Login")
        with st.form("log_f"):
            u, p = st.text_input("Username"), st.text_input("Password", type="password")
            if st.form_submit_button("Masuk"):
                user = login_user(u, p)
                if user:
                    st.session_state.logged_in, st.session_state.user_id, st.session_state.username = True, user[0], user[1]
                    st.rerun()
                else: st.error("Salah password/username.")
else:
    st.sidebar.success(f"User: {st.session_state.username}")
    app_menu = st.sidebar.radio("Navigasi", ["Dashboard", "Manage Data", "AI Analysis", "Reports", "Settings"])
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()

    # --- DASHBOARD ---
    if app_menu == "Dashboard":
        st.title("Dashboard Strategis")
        df_m = get_matches(st.session_state.user_id)
        df_r = get_ai_reports(st.session_state.user_id)
        api_key, _ = get_user_settings(st.session_state.user_id)
        
        # Metrik Utama
        c1, c2, c3 = st.columns(3)
        c1.metric("Database Pertandingan", f"{len(df_m)} Match")
        c2.metric("Analisa AI Terbit", f"{len(df_r)} Laporan")
        c3.metric("API Status", "Aktif ✅" if api_key else "Belum Set ❌")
        
        st.divider()
        
        # Visualisasi Data (Grafik & Tabel Aktivitas)
        col_chart, col_recent = st.columns([2, 1])
        
        with col_chart:
            st.subheader("📊 Tren Input Data Harian")
            if not df_m.empty:
                # Mengelompokkan data berdasarkan tanggal untuk grafik
                chart_data = df_m.groupby('match_date').size().reset_index(name='Jumlah')
                chart_data = chart_data.set_index('match_date')
                st.bar_chart(chart_data)
            else:
                st.info("Belum ada data untuk menampilkan grafik tren.")
                
        with col_recent:
            st.subheader("⚡ Analisis AI Terakhir")
            if not df_r.empty:
                # Menampilkan 5 analisis terbaru
                recent_reports = df_r[['home_team', 'away_team', 'match_date']].head(5)
                st.dataframe(recent_reports, use_container_width=True, hide_index=True)
            else:
                st.info("Mesin AI belum dijalankan.")

    # --- MANAGE DATA ---
    elif app_menu == "Manage Data":
        st.title("Manajemen Data Sepak Bola")
        t1, t2 = st.tabs(["Lihat Data", "Tambah Data"])
        with t2:
            with st.form("add_f"):
                d = st.date_input("Tanggal")
                h, a = st.text_input("Home"), st.text_input("Away")
                s = st.text_area("Statistik/Anomali")
                if st.form_submit_button("Simpan"):
                    add_match(st.session_state.user_id, d, h, a, s)
                    st.success("Tersimpan!")
            
            st.divider()
            
            # --- TAMBAHAN FITUR: DOWNLOAD TEMPLATE ---
            st.subheader("📥 Import Massal (Bulk Import)")
            st.info("Silakan download template CSV di bawah ini agar format data Anda sesuai dengan sistem.")
            
            template_df = pd.DataFrame({
                "match_date": ["2026-05-10", "2026-05-11"],
                "home_team": ["Arsenal", "Real Madrid"],
                "away_team": ["Chelsea", "Barcelona"],
                "stats_json": ["Home win streak 5x", "Striker utama tim away cedera"]
            })
            
            st.download_button(
                label="⬇️ Download Template CSV",
                data=template_df.to_csv(index=False).encode('utf-8'),
                file_name="template_import_pertandingan.csv",
                mime="text/csv"
            )
            
            # --- UPLOAD FILE ---
            up = st.file_uploader("Upload File Anda (CSV/XLSX yang sudah diisi)")
            if st.button("Import Now") and up:
                try:
                    df_up = pd.read_csv(up) if up.name.endswith('.csv') else pd.read_excel(up)
                    
                    # Validasi Header
                    required_cols = ['match_date', 'home_team', 'away_team', 'stats_json']
                    if all(col in df_up.columns for col in required_cols):
                        for _, r in df_up.iterrows():
                            if pd.notna(r['home_team']) and pd.notna(r['away_team']):
                                add_match(st.session_state.user_id, r['match_date'], r['home_team'], r['away_team'], r['stats_json'])
                        st.success("✅ Bulk Import Berhasil!")
                    else:
                        st.error(f"Format salah! Pastikan header kolom adalah: {', '.join(required_cols)}")
                except Exception as e:
                    st.error(f"Gagal memproses file: {e}")

        with t1:
            st.subheader("Database Pertandingan")
            df_display = get_matches(st.session_state.user_id)
            if not df_display.empty:
                
                # --- TAMBAHAN FITUR: SEARCH / FILTER DATA ---
                search_query = st.text_input("🔍 Cari Tim (Home/Away)...", placeholder="Ketik nama tim, misal: Arsenal")
                
                if search_query:
                    # Filter dataframe berdasarkan pencarian (case-insensitive)
                    mask = df_display['home_team'].str.contains(search_query, case=False, na=False) | \
                           df_display['away_team'].str.contains(search_query, case=False, na=False)
                    df_filtered = df_display[mask]
                else:
                    df_filtered = df_display
                
                # Tampilkan data yang sudah difilter
                st.dataframe(df_filtered, use_container_width=True, hide_index=True)
                
                # Tambahan Fitur Export CSV Data Pertandingan
                csv_data = df_filtered.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Data (CSV)",
                    data=csv_data,
                    file_name="database_pertandingan.csv",
                    mime="text/csv"
                )
                
                st.divider()
                st.subheader("⚙️ Hapus Data")
                col_del1, col_del2 = st.columns(2)
                
                with col_del1:
                    did = st.number_input("Hapus ID", step=1)
                    if st.button("Hapus 1 Data"):
                        delete_match(did, st.session_state.user_id)
                        st.rerun()
                        
                with col_del2:
                    st.warning("⚠️ Bahaya: Hapus Seluruh Database")
                    confirm_reset = st.checkbox("Saya yakin ingin mereset SEMUA data")
                    if st.button("🚨 Reset Semua Data", type="primary", disabled=not confirm_reset):
                        delete_all_matches(st.session_state.user_id)
                        st.success("Seluruh data berhasil dihapus!")
                        st.rerun()
            else:
                st.info("Belum ada data.")

    # --- AI ANALYSIS ---
    elif app_menu == "AI Analysis":
        st.title("AI Prediction Engine")
        df_m = get_matches(st.session_state.user_id)
        if df_m.empty: st.warning("Isi data dulu.")
        else:
            teams = sorted(list(set(df_m['home_team'].tolist() + df_m['away_team'].tolist())))
            
            st.subheader("1. Pilih Tim Pertandingan")
            c_a, c_b = st.columns(2)
            h_s = c_a.selectbox("Home", teams)
            a_s = c_b.selectbox("Away", teams)
            
            st.subheader("2. Pilih Jenis Prediksi (Odds)")
            odds_type = st.radio("Jenis Pasar:", ["1X2 (Win/Draw/Loss)", "Over/Under (Total Gol)"], horizontal=True)
            ou_threshold = 2.5
            if odds_type == "Over/Under (Total Gol)":
                ou_threshold = st.number_input("Batas Over/Under (Misal: 2.5, 3.0)", min_value=0.5, step=0.25, value=2.5, format="%.2f")
            
            st.divider()
            if st.button("Analis Sekarang 🚀", type="primary"):
                m_row = df_m[(df_m['home_team']==h_s) & (df_m['away_team']==a_s)]
                if m_row.empty: st.error("Match tidak ditemukan di DB.")
                elif h_s == a_s: st.error("Tim Home dan Away tidak boleh sama!")
                else:
                    api, mod = get_user_settings(st.session_state.user_id)
                    cur_m = m_row.iloc[0]
                    # Pastikan ID terbaca sebagai integer murni
                    match_id_real = int(cur_m['id'])
                    
                    hist = get_match_history(st.session_state.user_id, h_s, a_s, match_id_real)
                    h_txt = "\n".join([f"- {r['match_date']}: {r['home_team']} vs {r['away_team']} ({r['stats_json']})" for _,r in hist.iterrows()])
                    
                    # --- MENYUSUN PROMPT DINAMIS SESUAI ODDS ---
                    if odds_type == "1X2 (Win/Draw/Loss)":
                        task_instruction = """Tugas Anda:
1. Analisis tren performa berdasarkan Histori Masa Lalu dibandingkan dengan Catatan Saat Ini.
2. Berikan prediksi 1X2 (Home Win / Draw / Away Win) secara tegas.
3. Berikan probabilitas persentase.
4. Berikan 3 poin alasan strategis mengapa histori tersebut mempengaruhi prediksi ini."""
                        report_type = "WDL (1X2)"
                    else:
                        task_instruction = f"""Tugas Anda:
1. Analisis tren skor, produktivitas gol, dan pertahanan berdasarkan Histori Masa Lalu dibandingkan dengan Catatan Saat Ini.
2. Berikan prediksi OVER atau UNDER untuk batas {ou_threshold} gol secara tegas.
3. Berikan probabilitas persentase (Over {ou_threshold}: ...%, Under {ou_threshold}: ...%).
4. Berikan 3 poin alasan strategis yang fokus HANYA pada potensi jumlah gol di pertandingan ini."""
                        report_type = f"Over/Under ({ou_threshold})"

                    p = f"""Analisa Match: {h_s} vs {a_s}
Stats Saat Ini: {cur_m['stats_json']}

Histori Performa Masa Lalu:
{h_txt if h_txt else 'TIDAK ADA HISTORI TERDAHULU'}

{task_instruction}
Gunakan format markdown yang profesional."""
                    
                    with st.spinner(f"AI sedang berpikir menganalisa pasar {report_type}..."):
                        # Tangkap status API secara eksplisit (True / False)
                        is_success, res = call_openrouter_api(api, mod, p)
                        
                        if is_success:
                            add_ai_report(st.session_state.user_id, match_id_real, report_type, res)
                            st.success("✅ Analisa selesai dan otomatis tersimpan ke Arsip (Reports)!")
                            st.markdown(res)
                        else: 
                            st.error(res)

    # --- REPORTS ---
    elif app_menu == "Reports":
        st.title("Arsip Laporan AI")
        df_r = get_ai_reports(st.session_state.user_id)
        if df_r.empty: st.info("Belum ada laporan.")
        else:
            st.dataframe(df_r[['id', 'match_date', 'home_team', 'away_team', 'created_at']], use_container_width=True)
            
            # Tambahan Fitur Export CSV Arsip Laporan
            csv_rep = df_r.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Arsip Laporan (CSV)",
                data=csv_rep,
                file_name="arsip_laporan_ai.csv",
                mime="text/csv"
            )
            
            st.divider()
            rep_id = st.selectbox("Pilih ID Laporan untuk Detail:", df_r['id'].tolist())
            if st.button("Lihat Detail Analisa"):
                detail = df_r[df_r['id'] == rep_id]['insight_output'].values[0]
                st.subheader(f"Detail Laporan #{rep_id}")
                st.markdown(detail)

    # --- SETTINGS ---
    elif app_menu == "Settings":
        st.title("Settings")
        api, mod = get_user_settings(st.session_state.user_id)
        with st.form("s_f"):
            n_api = st.text_input("OpenRouter Key", value=api, type="password")
            n_mod = st.text_input("Model ID", value=mod)
            if st.form_submit_button("Save"):
                save_user_settings(st.session_state.user_id, n_api, n_mod)
                st.success("Saved!")