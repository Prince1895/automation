import { Page } from 'playwright';
import { applyToJob, UserProfile } from './applier.js';
import { analyzeJob } from './matcher.js';
import { generateTailoredPDF } from './pdf_gen.js';
import { uploadToDrive } from './drive.js';
import pool from './db.js';
import { initDb } from './db.js';
import { sendNightlyReport } from './reporter.js';
import { monitorInbox } from './email_manager.js';
import dotenv from 'dotenv';
import cron from 'node-cron';
import fs from 'fs';
import { chromium } from 'playwright-extra';
import stealth from 'puppeteer-extra-plugin-stealth';

dotenv.config();
chromium.use(stealth());

const USER_PROFILE: UserProfile = {
    fullName: "Prince Kumar",
    email: process.env.EMAIL_USER || "prince.kumar@example.com",
    phone: process.env.EMAIL_PHONE || "+1234567890",
    location: process.env.EMAIL_LOCATION || "New York, NY",
    linkedinProfile: "https://linkedin.com/in/princekumar",
    portfolio: "https://princekumar.dev",
    github: "https://github.com/princekumar"
};

const RESUME_TEXT = `
[Insert Full Resume Text Here]
`;

async function runApplicationLoop() {
    console.log("🚀 Starting Career Pilot Application Loop...");

    try {
        const context = await chromium.launchPersistentContext(process.env.FIREFOX_PROFILE_PATH, {
            headless: false,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        });
        const page = await context.newPage();

        await page.goto('https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer%20Nodejs%20AWS');

        const jobCards = await page.locator('.job-card-container').all();
        console.log(`Found ${jobCards.length} potential jobs.`);

        for (let i = 0; i < jobCards.length; i++) {
            const card = jobCards[i];
            await card.click();
            await page.waitForTimeout(2000);

            const jd = await page.innerText('.jobs-description').catch(() => 'Job description not found');
            const company = await page.innerText('.job-details__company-name').catch(() => 'Unknown Company');
            const title = await page.innerText('.job-details__job-title').catch(() => 'Unknown Title');
            const url = page.url();

            console.log(`Analyzing: ${title} at ${company}...`);

            const analysis = await analyzeJob(RESUME_TEXT, jd);

            if (analysis.should_apply && analysis.match_score > 80) {
                console.log(`✅ High Match (${analysis.match_score}%). Tailoring documents...`);

                const pdfPath = await generateTailoredPDF({
                    name: USER_PROFILE.fullName,
                    company: company,
                    tailoredBullets: analysis.tailored_bullet_points,
                    coverLetter: analysis.cover_letter,
                    originalResumeHtml: ""
                }, `${company}_Resume.pdf`);

                const driveLink = await uploadToDrive(pdfPath, Buffer.from(''), `${company}_${new Date().toISOString().split('T')[0]}`);

                console.log(`Attempting to apply to ${company}...`);
                const applicationResult = await applyToJob(page, url, pdfPath, USER_PROFILE);

                if (applicationResult.success) {
                    console.log(`🎉 Successfully applied to ${company}!`);
                    await pool.query(
                        `INSERT INTO applications (company_name, job_title, job_url, match_score, resume_path, status)
                         VALUES ($1, $2, $3, $4, $5, 'Applied') ON CONFLICT (job_url) DO UPDATE SET status = 'Applied'`,
                        [company, title, url, analysis.match_score, driveLink]
                    );
                } else {
                    console.error(`❌ Failed to apply to ${company}: ${applicationResult.error}`);
                    await pool.query(
                        `INSERT INTO applications (company_name, job_title, job_url, match_score, resume_path, status)
                         VALUES ($1, $2, $3, $4, $5, 'Failed') ON CONFLICT (job_url) DO UPDATE SET status = 'Failed'`,
                        [company, title, url, analysis.match_score, driveLink]
                    );
                }
            } else {
                console.log(`⏭️ Skipping ${company} (Score: ${analysis.match_score}%)`);
            }
        }

        await context.close();
    } catch (error) {
        console.error("Loop Error:", error);
    }
}

async function start() {
    await initDb();

    cron.schedule('0 */6 * * *', () => {
        runApplicationLoop();
    });

    cron.schedule('0 23 * * *', () => {
        sendNightlyReport();
    });

    // Email Monitoring every 30 mins
    cron.schedule('*/30 * * * *', () => {
        monitorInbox();
    });

    runApplicationLoop();
}

start();
