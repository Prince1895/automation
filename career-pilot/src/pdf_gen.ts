import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

export async function generateTailoredPDF(data: {
    name: string,
    company: string,
    tailoredBullets: string[],
    coverLetter: string,
    originalResumeHtml: string
}, outputFileName: string) {
    const browser = await puppeteer.launch({ headless: true });
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
    const pdfPath = path.join(process.cwd(), 'output', outputFileName);

    if (!fs.existsSync(path.join(process.cwd(), 'output'))) {
        fs.mkdirSync(path.join(process.cwd(), 'output'));
    }

    await page.pdf({ path: pdfPath, format: 'A4', margin: { top: '1cm', bottom: '1cm', left: '1cm', right: '1cm' } });
    await browser.close();

    return pdfPath;
}
