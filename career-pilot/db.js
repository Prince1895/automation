import pg from 'pg';
import dotenv from 'dotenv';

dotenv.config();

const { Pool } = pg;
const pool = new Pool({
    host: process.env.DB_HOST,
    port: parseInt(process.env.DB_PORT || '5432'),
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
});

export async function initDb() {
    const query = `
    CREATE TABLE IF NOT EXISTS applications (
        id SERIAL PRIMARY KEY,
        company_name TEXT NOT NULL,
        job_title TEXT NOT NULL,
        job_url TEXT UNIQUE NOT NULL,
        match_score INTEGER,
        status TEXT DEFAULT 'Applied',
        resume_path TEXT,
        cover_letter_path TEXT,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS email_logs (
        id SERIAL PRIMARY KEY,
        application_id INTEGER REFERENCES applications(id),
        email_type TEXT,
        direction TEXT,
        content TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    `;
    try {
        await pool.query(query);
        console.log("Database initialized successfully.");
    } catch (error) {
        console.error("Database initialization failed:", error);
        throw error;
    }
}

export default pool;
