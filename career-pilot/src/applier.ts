import { Page } from 'playwright';

export interface UserProfile {
    fullName: string;
    email: string;
    phone: string;
    location: string;
    linkedinProfile: string;
    portfolio: string;
    github: string;
}

export async function applyToJob(page: Page, jobUrl: string, pdfPath: string, profile: UserProfile): Promise<{ success: boolean; error?: string }> {
    try {
        console.log(`Navigating to job URL: ${jobUrl}`);
        await page.goto(jobUrl);
        await page.waitForTimeout(2000);

        // Look for "Easy Apply" button
        const easyApplyButton = await page.locator('button:has-text("Easy Apply"), button:has-text("Apply Now")').first();
        if (!easyApplyButton.isVisible()) {
            return { success: false, error: 'Easy Apply button not found' };
        }

        await easyApplyButton.click();
        console.log('Clicked Easy Apply button');

        // Handle application form steps
        await handleApplicationForms(page, profile, pdfPath);

        // Final submission
        const submitButton = await page.locator('button:has-text("Submit application"), button:has-text("Submit")').first();
        if (submitButton.isVisible()) {
            await submitButton.click();
            console.log('Application submitted successfully');
        }

        return { success: true };
    } catch (error: any) {
        console.error(`Application error for ${jobUrl}:`, error);
        return { success: false, error: error.message };
    }
}

async function handleApplicationForms(page: Page, profile: UserProfile, pdfPath: string): Promise<void> {
    let currentStep = 0;
    const maxSteps = 10;

    while (currentStep < maxSteps) {
        // Check for "Next" or "Continue" buttons
        const nextButton = await page.locator('button:has-text("Next"), button:has-text("Continue"), button:has-text("Review")').first();

        if (!nextButton.isVisible()) break;

        // Handle common input fields
        await fillCommonFields(page, profile);

        // Handle file upload for resume if present
        const fileInput = await page.locator('input[type="file"]').first();
        if (fileInput.isVisible()) {
            await fileInput.setInputFiles(pdfPath);
            console.log('Uploaded tailored resume');
        }

        await nextButton.click();
        await page.waitForTimeout(1000);
        currentStep++;
    }
}

async function fillCommonFields(page: Page, profile: UserProfile): Promise<void> {
    // This is a simplified mapping. Real LinkedIn forms vary.
    const fields = [
        { selector: 'input[name="phone"]', value: profile.phone },
        { selector: 'input[name="city"]', value: profile.location },
        { selector: 'input[name="email"]', value: profile.email },
    ];

    for (const field of fields) {
        const input = await page.locator(field.selector).first();
        if (input.isVisible()) {
            await input.fill(field.value);
        }
    }
}
