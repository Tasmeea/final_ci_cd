import psycopg2
from datetime import datetime
import os

class DatabaseManager:
    def __init__(self):
        self.connection_string = os.getenv(
            'DATABASE_URL', 
            'postgresql://postgres:sarawak2024!@18.143.157.100:5432/visitors'
        )
        self.init_database()
    
    def get_connection(self):
        return psycopg2.connect(self.connection_string)
    
    def init_database(self):
        """Initialize database tables"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        CREATE TABLE IF NOT EXISTS visitors (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            destination_floor INTEGER NOT NULL,
                            purpose TEXT,
                            duration_hours INTEGER DEFAULT 1,
                            entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            image_path TEXT,
                            status VARCHAR(50) DEFAULT 'pending'
                        )
                    ''')
                    conn.commit()
        except Exception as e:
            print(f"Database initialization error: {e}")
    
    def create_visitor_record(self, name, floor, purpose, duration):
        """Create a new visitor record"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        INSERT INTO visitors (name, destination_floor, purpose, duration_hours, status)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    ''', (name, floor, purpose, duration, 'approved'))
                    visitor_id = cur.fetchone()[0]
                    conn.commit()
                    return visitor_id
        except Exception as e:
            print(f"Database error: {e}")
            return None
    
    def update_visitor_image(self, visitor_id, image_path):
        """Update visitor record with image path"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        UPDATE visitors SET image_path = %s WHERE id = %s
                    ''', (image_path, visitor_id))
                    conn.commit()
        except Exception as e:
            print(f"Database update error: {e}")