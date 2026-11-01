import imap from 'imap-simple';
import nodemailer from 'nodemailer';
import { analyzeJob } from './matcher.js';
import pool from './db.js';
import dotenv from 'dotenv';

dotenv.config();

const EMAIL_CONFIG = {
    imap: {
        user: process.env.EMAIL_USER,
        password: process.env.EMAIL_PASSWORD,
        host: 'imap.gmail.com',
        port: 993,
        tls: true,
        authTimeout: 3000
    },
    smtp: {
        service: 'gmail',
        auth: {
            user: process.env.EMAIL_USER,
            pass: process.env.EMAIL_PASSWORD
        }
    }
};

const transporter = nodemailer.createTransport(EMAIL_CONFIG.smtp);

export async function monitorInbox() {
    console.log("Checking inbox for recruiter replies...");
    try {
        const connection = await imap.connect({ imap: EMAIL_CONFIG.imap });
        await connection.openBox('INBOX');

        const searchCriteria = [
            ['UNSEEN', true],
            ['TEXT', 'Interview'],
            ['TEXT', 'Application']
        ];

        const messages = await connection.search(searchCriteria);
        console.log(`Found ${messages.length} new potential recruiter emails.`);

        for (const messageId of messages) {
            const msg = await connection.fetchOne(messageId, { bodies: '' });
            const body = msg.parts[0].body;
            const from = msg.from.text;
            const subject = msg.subject;

            console.log(`Processing email from ${from}: ${subject}`);

            const replyBody = await generateReply(body, from);
            if (replyBody) {
                await sendEmail(from, `Re: ${subject}`, replyBody);
                await pool.query(
                    `INSERT INTO email_logs (email_address, message_type, content, direction)
                     VALUES ($1, 'Reply', $2, 'Outbound')`,
                    [from, replyBody]
                );
            }
        }

        await connection.end();
    } catch (error) {
        console.error("Email Monitoring Error:", error);
    }
}

async function generateReply(emailBody: string, sender: string): Promise<string | null> {
    try {
        // This uses the same LLM logic as matcher.ts (conceptual)
        // In a real implementation, this would be a separate call to OpenRouter
        console.log(`Generating LLM reply for ${sender}...`);
        return `Dear Recruiter,\n\nThank you for reaching out! I am very interested in this opportunity. Please let me know your availability for a call.\n\nBest regards,\nPrince Kumar`;
    } catch (error) {
        console.error("Reply Generation Error:", error);
        return null;
    }
}

export async function sendEmail(to: string, subject: string, body: string): Promise<void> {
    await transporter.sendMail({
        from: EMAIL_CONFIG.smtp.auth.user,
        to,
        subject,
        text: body
    });
    console.log(`Email sent to ${to}`);
}

export async function sendColdEmail(recruiterEmail: string, company: string, tailoredPitch: string): Promise<void> {
    const subject = `Inquiry: Software Engineering Roles at ${company}`;
    const body = `Hi,\n\n${tailoredPitch}\n\nI've attached my resume and would love to connect.\n\nBest,\nPrince Kumar`;
    await sendEmail(recruiterEmail, subject, body);
}
