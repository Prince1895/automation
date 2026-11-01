"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.initDb = initDb;
const pg_1 = require("pg");
const dotenv_1 = __importDefault(require("dotenv"));
dotenv_1.default.config();
const pool = new pg_1.Pool({
    host: process.env.DB_HOST,
    port: parseInt(process.env.DB_PORT || '5432'),
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME,
});
async function initDb() {
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
        email_type TEXT, -- 'Recruiter', 'System'
        direction TEXT, -- 'Inbound', 'Outbound'
        content TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    `;
    try {
        await pool.query(query);
        console.log("Database initialized successfully.");
    }
    catch (error) {
        console.error("Database initialization failed:", error);
        throw error;
    }
}
exports.default = pool;
//# sourceMappingURL=db.js.map