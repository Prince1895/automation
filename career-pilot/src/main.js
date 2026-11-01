"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const playwright_extra_1 = require("playwright-extra");
const playwright_extra_plugin_stealth_1 = __importDefault(require("playwright-extra-plugin-stealth"));
const matcher_1 = require("./matcher");
const pdf_gen_1 = require("./pdf_gen");
const drive_1 = require("./drive");
const db_1 = __importDefault(require("./db"));
const db_2 = require("./db");
const reporter_1 = require("./reporter");
const dotenv_1 = __importDefault(require("dotenv"));
const node_cron_1 = __importDefault(require("node-cron"));
const fs_1 = __importDefault(require("fs"));
dotenv_1.default.config();
playwright_extra_1.chromium.use((0, playwright_extra_plugin_stealth_1.default)());
const RESUME_TEXT = `
[Insert Full Resume Text Here - I will load this from a file]
`;
async function runApplicationLoop() {
    console.log("🚀 Starting Career Pilot Application Loop...");
    try {
        // 1. Launch Stealth Browser with Firefox Profile
        const browser = await playwright_extra_1.chromium.launch({
            headless: false,
            args: [
                `--user-data-dir=${process.env.FIREFOX_PROFILE_PATH}`,
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        });
        const context = await browser.newContext();
        const page = await context.newPage();
        // 2. Target Job Boards (Example: LinkedIn)
        await page.goto('https://www.linkedin.com/jobs/search/?keywords=Backend%20Engineer%20Nodejs%20AWS');
        // Logic to scrape job cards (Simplified for the start)
        const jobCards = await page.$$('.job-card-container');
        console.log(`Found ${jobCards.length} potential jobs.`);
        for (const card of jobCards) {
            await card.click();
            await page.waitForTimeout(2000);
            const jd = await page.innerText('.jobs-description');
            const company = await page.innerText('.job-details__company-name');
            const title = await page.innerText('.job-details__job-title');
            const url = page.url();
            console.log(`Analyzing: ${title} at ${company}...`);
            // 3. LLM Analysis
            const analysis = await (0, matcher_1.analyzeJob)(RESUME_TEXT, jd);
            if (analysis.should_apply && analysis.match_score > 80) {
                console.log(`✅ High Match (${analysis.match_score}%). Tailoring documents...`);
                // 4. Tailor & Generate PDF
                const pdfPath = await (0, pdf_gen_1.generateTailoredPDF)({
                    name: "Prince Kumar",
                    company: company,
                    tailoredBullets: analysis.tailored_bullet_points,
                    coverLetter: analysis.cover_letter,
                    originalResumeHtml: ""
                }, `${company}_Resume.pdf`);
                // 5. Upload to Google Drive
                const driveLink = await (0, drive_1.uploadToDrive)(pdfPath, Buffer.from(''), `${company}_${new Date().toISOString().split('T')[0]}`);
                // 6. Log to Database
                await db_1.default.query(`INSERT INTO applications (company_name, job_title, job_url, match_score, resume_path)
                     VALUES ($1, $2, $3, $4, $5) ON CONFLICT (job_url) DO NOTHING`, [company, title, url, analysis.match_score, driveLink]);
                // 7. Auto-Apply (The clicking part)
                // This part is highly site-specific and will be refined in the loop
                console.log(`Applying to ${company}...`);
                // await page.click('button:has-text("Easy Apply")');
                // ... form filling logic ...
            }
            else {
                console.log(`⏭️ Skipping ${company} (Score: ${analysis.match_score}%)`);
            }
        }
        await browser.close();
    }
    catch (error) {
        console.error("Loop Error:", error);
    }
}
async function start() {
    await (0, db_2.initDb)();
    // Run application loop every 6 hours
    node_cron_1.default.schedule('0 */6 * * *', () => {
        runApplicationLoop();
    });
    // Run nightly report at 11 PM
    node_cron_1.default.schedule('0 23 * * *', () => {
        (0, reporter_1.sendNightlyReport)();
    });
    // Immediate first run
    runApplicationLoop();
}
start();
//# sourceMappingURL=main.js.map