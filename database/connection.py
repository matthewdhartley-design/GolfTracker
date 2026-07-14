import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Load local .env variables
load_dotenv()

DATABASE_URL = os.getenv("NEON_DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("❌ NEON_DATABASE_URL not found in .env file.")

# Resolve Postgres protocol names
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Establish connection engine
engine = create_engine(DATABASE_URL)

def get_db_connection():
    """Returns a connection from the SQLAlchemy engine connection pool."""
    return engine.connect()

# ... (your existing connection.py code is up here)

# This block only runs when you execute connection.py directly, 
# but gets ignored when you import it into other files later.
if __name__ == "__main__":
    from sqlalchemy import text
    
    print("🔄 Testing database connection...")
    try:
        # 1. Grab a connection from the pool
        with get_db_connection() as conn:
            # 2. Run a simple query to ping the server
            result = conn.execute(text("SELECT 1")).scalar()
            
            # 3. Check if our tables are actually there
            tables_query = text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'golf';
            """)
            tables = conn.execute(tables_query).fetchall()
            
        if result == 1:
            print("✅ Database connection successful! Neon is responding.")
            print("\n📬 Tables found in your database:")
            for t in tables:
                print(f"  - {t[0]}")
        else:
            print("❓ Connection established, but returned an unexpected result.")
            
    except Exception as e:
        print(f"❌ Database connection failed!")
        print(f"Error Details: {e}")