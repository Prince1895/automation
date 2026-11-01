"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.generateTailoredPDF = generateTailoredPDF;
const puppeteer_1 = __importDefault(require("puppeteer"));
const fs_1 = __importDefault(require("fs"));
const path_1 = __importDefault(require("path"));
async function generateTailoredPDF(data, outputFileName) {
    const browser = await puppeteer_1.default.launch({ headless: true });
    const page = await browser.newPage();
    // Simple professional template injection
    const htmlContent = `
    <html>
    <head>
        <style>
            body { font-family: 'Arial', sans-serif; padding: 40px; line-height: 1.5; color: #333; }
            .header { text-align: center; border-bottom: 2px solid #444; padding-bottom: 10px; }
            .section { margin-top: 20px; }
            .section-title { font-weight: bold; text-transform: uppercase; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
            .bullet-list { margin-left: 20px; }
            .cover-letter { white-space: pre-wrap; margin-bottom: 40px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>${data.name}</h1>
            <p>Tailored for ${data.company}</p>
        </div>

        <div class="section">
            <div class="section-title">Tailored Cover Letter</div>
            <div class="cover-letter">${data.coverLetter}</div>
        </div>

        <div class="section">
            <div class="section-title">Resume Highlights</div>
            <ul class="bullet-list">
                ${data.tailoredBullets.map(b => `<li>${b}</li>`).join('')}
            </ul>
        </div>
    </body>
    </html>
    `;
    await page.setContent(htmlContent);
    const pdfPath = path_1.default.join(process.cwd(), 'output', outputFileName);
    if (!fs_1.default.existsSync(path_1.default.join(process.cwd(), 'output'))) {
        fs_1.default.mkdirSync(path_1.default.join(process.cwd(), 'output'));
    }
    await page.pdf({ path: pdfPath, format: 'A4', margin: { top: '1cm', bottom: '1cm', left: '1cm', right: '1cm' } });
    await browser.close();
    return pdfPath;
}
//# sourceMappingURL=pdf_gen.js.map