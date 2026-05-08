# Gunakan image Python yang ringan
FROM python:3.11-slim

# Set folder kerja di dalam container
WORKDIR /app

# Salin requirements dulu agar caching pip bekerja efisien
COPY requirements.txt .

# Install semua dependensi
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh file aplikasi (termasuk app.py dan csv jika ada)
COPY . .

# Buka port default Streamlit
EXPOSE 8501

# Jalankan aplikasi
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]