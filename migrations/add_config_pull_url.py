#!/usr/bin/env python3
"""
Migration script to add last_config_pull_url column to gateway_servers and gateway_clients tables.
"""
import sqlite3
import sys
import os

def migrate_database(db_path):
    """
    Add last_config_pull_url column to gateway_servers and gateway_clients tables.
    """
    print(f"Migrating database at {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(gateway_servers)")
        columns = {col[1] for col in cursor.fetchall()}
        
        if "last_config_pull_url" not in columns:
            print("Adding last_config_pull_url column to gateway_servers table")
            cursor.execute("ALTER TABLE gateway_servers ADD COLUMN last_config_pull_url VARCHAR(512)")
        else:
            print("Column last_config_pull_url already exists in gateway_servers table")
        
        # Check clients table
        cursor.execute("PRAGMA table_info(gateway_clients)")
        columns = {col[1] for col in cursor.fetchall()}
        
        if "last_config_pull_url" not in columns:
            print("Adding last_config_pull_url column to gateway_clients table")
            cursor.execute("ALTER TABLE gateway_clients ADD COLUMN last_config_pull_url VARCHAR(512)")
        else:
            print("Column last_config_pull_url already exists in gateway_clients table")
        
        # Commit the changes
        conn.commit()
        print("Migration completed successfully!")
    
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Default database path - adjust as needed
    default_db_path = os.path.join("data", "app.db")
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = default_db_path
    
    # Get absolute path if relative
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), db_path)
    
    migrate_database(db_path)
