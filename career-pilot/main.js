import { chromium } from 'playwright-extra';
import stealth from 'playwright-extra-plugin-stealth';
import { analyzeJob } from './matcher.js';
import { initDb } from './db.js';
import pool from './db.js';
import dotenv from 'dotenv';
import cron from 'node-cron';

dotenv.config();
chromium.use(stealth());

const RESUME_TEXT = `
Prince Kumar - Backend Engineer
Skills: Node.js, AWS, PostgreSQL, Redis, Docker, TypeScript.
Experience: Backend Lead at Accesco Living, built distributed API gateway and cloud cost engine.
`;

async function runApplicationLoop() {
    console.log("🚀 Starting Career Pilot Application Loop...");
    try {
        const browser = await chromium.launch({
            headless: false,
            args: [`--user-data-dir=${process.env.FIREFOX_PROFILE_PATH}`, '--no-sandbox']
        });
        const context = await browser.newContext();
        const page = await context.newPage();

        await page.goto('https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer%20Nodejs%20AWS');
        console.log("Page loaded. Searching for jobs...");
        
        const jobCards = await page.$$('.job-card-container');
        console.log(`Found ${jobCards.length} potential jobs.`);

        // Basic dry run for the first job
        if (jobCards.length > 0) {
            await jobCards[0].click();
            await page.waitForTimeout(3000);
            const jd = await page.innerText('.jobs-description');
            const company = await page.innerText('.job-details__company-name');
            const title = await page.innerText('.job-details__job-title');
            const url = page.url();

            console.log(`Analyzing: ${title} at ${company}...`);
            const analysis = await analyzeJob(RESUME_TEXT, jd);
            console.log(`Analysis Result: ${analysis.match_score}% match.`);
        }

        await browser.close();
    } catch (error) {
        console.error("Loop Error:", error);
    }
}

async function start() {
    await initDb();
    cron.schedule('0 */6 * * *', () => runApplicationLoop());
    runApplicationLoop();
}

start();
