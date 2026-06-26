import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "4203FuSuY",
    "database": "houseai_db",
    "port": 3306
}

def get_db_connection():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print("MySQL connection error:", e)
        return None
    
if __name__ == "__main__":
    conn = get_db_connection()

    if conn and conn.is_connected():
        print("✅ MySQL bağlantısı başarılı!")
        print("Database:", conn.database)
        conn.close()
    else:
        print("❌ MySQL bağlantısı başarısız!")