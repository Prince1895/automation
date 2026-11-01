"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const matcher_1 = require("./matcher");
const pdf_gen_1 = require("./pdf_gen");
const drive_1 = require("./drive");
const db_1 = require("./db");
const db_2 = __importDefault(require("./db"));
const dotenv_1 = __importDefault(require("dotenv"));
dotenv_1.default.config();
async function testRun() {
    console.log("🧪 Starting Dry Run Test...");
    try {
        // 1. Initialize Database
        await (0, db_1.initDb)();
        console.log("✅ Database initialized.");
        // 2. Mock Data for testing
        const mockResume = `
        Prince Kumar - Backend Engineer
        Skills: Node.js, AWS, PostgreSQL, Redis, Docker, TypeScript.
        Experience: Backend Lead at Accesco Living, built distributed API gateway and cloud cost engine.
        `;
        const mockJD = `
        We are looking for a Senior Backend Engineer with experience in Node.js and AWS.
        The ideal candidate should be proficient in PostgreSQL and have experience with Redis for caching.
        Responsibilities include optimizing API latency and managing cloud infrastructure.
        `;
        console.log("Analyzing mock job...");
        // 3. Test Matcher
        const analysis = await (0, matcher_1.analyzeJob)(mockResume, mockJD);
        console.log("Analysis Result:", JSON.stringify(analysis, null, 2));
        if (analysis.should_apply) {
            console.log("✅ Job matches! Testing PDF generation...");
            // 4. Test PDF Generation
            const pdfPath = await (0, pdf_gen_1.generateTailoredPDF)({
                name: "Prince Kumar",
                company: "Test Company Inc",
                tailoredBullets: analysis.tailored_bullet_points,
                coverLetter: analysis.cover_letter,
                originalResumeHtml: ""
            }, "test_resume.pdf");
            console.log(`✅ PDF generated at: ${pdfPath}`);
            // 5. Test Drive Upload (This will fail if google-credentials.json is missing)
            try {
                console.log("Testing Google Drive upload...");
                const driveLink = await (0, drive_1.uploadToDrive)(pdfPath, Buffer.from(''), "Test_Company_DryRun");
                console.log(`✅ Uploaded to Drive: ${driveLink}`);
            }
            catch (e) {
                console.warn("⚠️ Drive upload failed (expected if credentials are missing):", e.message);
            }
            // 6. Test Database Logging
            await db_2.default.query(`INSERT INTO applications (company_name, job_title, job_url, match_score, resume_path)
                 VALUES ($1, $2, $3, $4, $5)`, ["Test Company Inc", "Backend Engineer", "https://example.com/test", analysis.match_score, "local_test_path"]);
            console.log("✅ Logged to Database.");
        }
        else {
            console.log("❌ Job did not match. Test skipped application phase.");
        }
        console.log("\n🎉 Dry Run Complete! Everything is working as expected.");
    }
    catch (error) {
        console.error("❌ Test failed:", error);
    }
    finally {
        await db_2.default.end();
    }
}
testRun();
//# sourceMappingURL=test.js.map