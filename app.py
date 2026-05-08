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

# Jalankan inisialisasi database saat aplikasi pertama jalan
init_db()

# ==========================================
# 2. AUTHENTICATION LOGIC
# ==========================================
def hash_password(password):
    """Hashing password menggunakan SHA-256 untuk keamanan dasar."""
    return hashlib.sha256(str.encode(password)).hexdigest()

def register_user(username, password):
    """Menambahkan user baru ke database."""
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
    """Mengecek kredensial login."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE username=? AND password=?", (username, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

# ==========================================
# 2.5 USER SETTINGS LOGIC
# ==========================================
def get_user_settings(user_id):
    """Mengambil API Key dan Pilihan Model untuk user tertentu."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT openrouter_api_key, preferred_model FROM user_settings WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res if res else ("", "gpt-4o")

def save_user_settings(user_id, api_key, model):
    """Menyimpan atau memperbarui pengaturan user."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM user_settings WHERE user_id=?", (user_id,))
    if c.fetchone():
        c.execute("UPDATE user_settings SET openrouter_api_key=?, preferred_model=? WHERE user_id=?", (api_key, model, user_id))
    else:
        c.execute("INSERT INTO user_settings (user_id, openrouter_api_key, preferred_model) VALUES (?, ?, ?)", (user_id, api_key, model))
    conn.commit()
    conn.close()

# ==========================================
# 2.6 CRUD LOGIC (MAIN DATA)
# ==========================================
def add_match(user_id, match_date, home_team, away_team, stats_json):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO main_data (user_id, match_date, home_team, away_team, stats_json)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, str(match_date), home_team, away_team, stats_json))
    conn.commit()
    conn.close()

def get_matches(user_id):
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, match_date, home_team, away_team, stats_json, created_at FROM main_data WHERE user_id=? ORDER BY id DESC", conn, params=(user_id,))
    conn.close()
    return df

def delete_match(match_id, user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM main_data WHERE id=? AND user_id=?", (match_id, user_id))
    conn.commit()
    conn.close()

def get_match_history(user_id, team1, team2, current_match_id):
    """Mengambil data histori pertandingan terdahulu untuk tim yang dipilih."""
    conn = get_connection()
    # Mencari pertandingan di mana team1 atau team2 terlibat, kecuali pertandingan yang sedang dipilih saat ini
    query = """
        SELECT match_date, home_team, away_team, stats_json 
        FROM main_data 
        WHERE user_id = ? 
        AND id != ?
        AND (home_team = ? OR away_team = ? OR home_team = ? OR away_team = ?)
        ORDER BY match_date DESC LIMIT 10
    """
    df_history = pd.read_sql_query(query, conn, params=(user_id, current_match_id, team1, team1, team2, team2))
    conn.close()
    return df_history

# ==========================================
# 2.7 AI REPORTS LOGIC
# ==========================================
def add_ai_report(user_id, match_id, analysis_type, insight_output):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO ai_analysis_history (user_id, match_id, analysis_type, insight_output)
        VALUES (?, ?, ?, ?)
    ''', (user_id, match_id, analysis_type, insight_output))
    conn.commit()
    conn.close()

def get_ai_reports(user_id):
    conn = get_connection()
    query = '''
        SELECT a.id, a.match_id, m.home_team, m.away_team, a.analysis_type, a.insight_output, a.created_at
        FROM ai_analysis_history a
        JOIN main_data m ON a.match_id = m.id
        WHERE a.user_id=? ORDER BY a.id DESC
    '''
    df = pd.read_sql_query(query, conn, params=(user_id,))
    conn.close()
    return df

# ==========================================
# 2.8 OPENROUTER API LOGIC
# ==========================================
def call_openrouter_api(api_key, model, prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=40)
        response.raise_for_status() 
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.HTTPError as errh:
        return f"Error API HTTP: {errh}"
    except Exception as e:
        return f"Error Sistem: {str(e)}"

# ==========================================
# 3. SESSION STATE INITIALIZATION
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = ""

# ==========================================
# 4. MAIN UI & ROUTING
# ==========================================
st.set_page_config(page_title="Football Engine", layout="wide")

st.sidebar.title("Navigasi")

if not st.session_state.logged_in:
    menu = st.sidebar.radio("Menu", ["Login", "Register"])
    
    if menu == "Register":
        st.title("Register Akun")
        with st.form("register_form"):
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            submit_register = st.form_submit_button("Register")
            
            if submit_register:
                if register_user(new_username, new_password):
                    st.success("Registrasi berhasil! Silakan pindah ke menu Login.")
                else:
                    st.error("Username sudah terdaftar! Pilih yang lain.")
                    
    elif menu == "Login":
        st.title("Login Sistem")
        with st.form("login_form"):
            login_username = st.text_input("Username")
            login_password = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Login")
            
            if submit_login:
                user = login_user(login_username, login_password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user[0]
                    st.session_state.username = user[1]
                    st.rerun() 
                else:
                    st.error("Username atau Password salah!")

else:
    st.sidebar.success(f"Aktif: {st.session_state.username}")
    app_menu = st.sidebar.radio("Menu Utama", ["Dashboard", "Manage Data", "AI Analysis", "Settings"])
    
    st.sidebar.divider()
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = ""
        st.rerun()
        
    if app_menu == "Dashboard":
        st.title("Dashboard Kontrol Strategis")
        st.success("System Ready ✅")
        st.write(f"Selamat datang, **{st.session_state.username}**!")
        
        total_data = len(get_matches(st.session_state.user_id))
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Data Tersimpan", f"{total_data} Pertandingan")
        col2.metric("Target Akurasi", "> 65%")
        col3.metric("Status AI API", "Terhubung" if get_user_settings(st.session_state.user_id)[0] else "Menunggu API Key")
        
    elif app_menu == "Manage Data":
        st.title("Manage Data (CRUD)")
        tab1, tab2 = st.tabs(["📋 Lihat Data", "➕ Input Data Baru"])
        
        with tab2:
            st.subheader("Input Manual Pertandingan")
            with st.form("input_match_form"):
                col1, col2 = st.columns(2)
                match_date = col1.date_input("Tanggal Pertandingan")
                home_team = col1.text_input("Tim Tuan Rumah (Home)")
                away_team = col2.text_input("Tim Tamu (Away)")
                stats_json = st.text_area("Variabel Statistik / Anomali (Catatan)", placeholder="Contoh: Formasi 4-3-3, Kiper cadangan main, Striker cedera...")
                
                submit_match = st.form_submit_button("Simpan Data Manual")
                if submit_match:
                    if home_team and away_team:
                        add_match(st.session_state.user_id, match_date, home_team, away_team, stats_json)
                        st.success(f"Pertandingan {home_team} vs {away_team} berhasil disimpan!")
                    else:
                        st.error("Nama tim wajib diisi!")
            
            st.divider()
            st.subheader("📥 Import Massal via Excel/CSV")
            uploaded_file = st.file_uploader("Upload file data (.csv / .xlsx)", type=["csv", "xlsx"])
            if st.button("Proses Import Data", type="primary"):
                if uploaded_file:
                    try:
                        df_import = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                        required_cols = ['match_date', 'home_team', 'away_team', 'stats_json']
                        if all(col in df_import.columns for col in required_cols):
                            for _, row in df_import.iterrows():
                                if pd.notna(row['home_team']) and pd.notna(row['away_team']):
                                    add_match(st.session_state.user_id, str(row['match_date']), row['home_team'], row['away_team'], row['stats_json'])
                            st.success("✅ Import Massal Berhasil!")
                        else:
                            st.error("Header kolom tidak sesuai!")
                    except Exception as e:
                        st.error(f"Error: {e}")
                        
        with tab1:
            st.subheader("Database Pertandingan")
            df_matches = get_matches(st.session_state.user_id)
            if not df_matches.empty:
                st.dataframe(df_matches, use_container_width=True, hide_index=True)
                st.divider()
                col_del1, _ = st.columns([1, 3])
                del_id = col_del1.number_input("ID Hapus", min_value=0, step=1)
                if col_del1.button("Hapus Data", type="primary"):
                    delete_match(del_id, st.session_state.user_id)
                    st.rerun()
            else:
                st.info("Belum ada data.")

    elif app_menu == "AI Analysis":
        st.title("Mesin Inferensi AI (Prediction Engine)")
        df_matches = get_matches(st.session_state.user_id)
        
        if df_matches.empty:
            st.warning("Input data dulu di menu Manage Data.")
        else:
            # Mengambil daftar tim unik dari kolom home_team dan away_team
            all_teams = pd.concat([df_matches['home_team'], df_matches['away_team']]).unique()
            all_teams_sorted = sorted([str(team) for team in all_teams])
            
            st.subheader("1. Pilih Tim Pertandingan")
            col_a, col_b = st.columns(2)
            
            home_select = col_a.selectbox("Pilih Tim Tuan Rumah (Home):", all_teams_sorted)
            away_select = col_b.selectbox("Pilih Tim Tamu (Away):", all_teams_sorted)
            
            if st.button("Jalankan AI Engine 🚀", type="primary"):
                if home_select == away_select:
                    st.error("Tim Home dan Away tidak boleh sama!")
                else:
                    # Mencari baris data yang cocok dengan pasangan tim tersebut
                    # Kita ambil yang terbaru (index pertama karena ORDER BY id DESC)
                    match_row_query = df_matches[(df_matches['home_team'] == home_select) & (df_matches['away_team'] == away_select)]
                    
                    if match_row_query.empty:
                        st.error(f"Data pertandingan spesifik {home_select} vs {away_select} tidak ditemukan di database.")
                        st.info("Pastikan Anda sudah menginput data untuk pasangan tim ini di menu 'Manage Data'.")
                    else:
                        match_row = match_row_query.iloc[0]
                        selected_match_id = int(match_row['id'])
                        
                        api_key, model = get_user_settings(st.session_state.user_id)
                        if not api_key:
                            st.error("Set API Key di menu Settings!")
                        else:
                            # --- AMBIL HISTORI TIM TERKAIT ---
                            df_history = get_match_history(st.session_state.user_id, home_select, away_select, selected_match_id)
                            history_text = "TIDAK ADA HISTORI TERDAHULU DI DATABASE."
                            if not df_history.empty:
                                history_text = "\n".join([
                                    f"- {row['match_date']}: {row['home_team']} vs {row['away_team']} | Catatan: {row['stats_json']}"
                                    for _, row in df_history.iterrows()
                                ])

                            # --- PROMPT ENGINE DENGAN KONTEKS HISTORI ---
                            prompt = f"""
Sebagai analis data sepak bola profesional, tinjau pertandingan ini:
DATA PERTANDINGAN SAAT INI:
- Tanggal: {match_row['match_date']}
- Tuan Rumah: {match_row['home_team']}
- Tamu: {match_row['away_team']}
- Catatan Saat Ini: {match_row['stats_json']}

HISTORI PERFORMA TIM DARI DATABASE (Konteks Masa Lalu):
{history_text}

Tugas Anda:
1. Analisis tren berdasarkan Histori Masa Lalu dibandingkan dengan Catatan Saat Ini.
2. Berikan prediksi WDL (Win/Draw/Loss) yang tegas.
3. Berikan probabilitas persentase.
4. Berikan 3 poin alasan strategis mengapa histori tersebut mempengaruhi prediksi ini.
Gunakan format markdown yang profesional.
"""
                            with st.spinner(f"Menganalisis {home_select} vs {away_select}..."):
                                ai_result = call_openrouter_api(api_key, model, prompt)
                                
                            if "Error" not in ai_result:
                                add_ai_report(st.session_state.user_id, selected_match_id, "Contextual WDL", ai_result)
                                st.markdown(ai_result)
                            else:
                                st.error(ai_result)

    elif app_menu == "Settings":
        st.title("Settings")
        current_api, current_model = get_user_settings(st.session_state.user_id)
        with st.form("set_form"):
            new_api = st.text_input("OpenRouter API Key", value=current_api, type="password")
            new_mod = st.text_input("Model ID", value=current_model)
            if st.form_submit_button("Simpan"):
                save_user_settings(st.session_state.user_id, new_api, new_mod)
                st.success("Tersimpan!")