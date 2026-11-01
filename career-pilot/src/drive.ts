import { google } from 'googleapis';
import dotenv from 'dotenv';
import fs from 'fs';

dotenv.config();

async function getDriveClient() {
    const auth = new google.auth.GoogleAuth({
        keyFile: process.env.GOOGLE_APPLICATION_CREDENTIALS,
        scopes: ['https://www.googleapis.com/auth/drive.file'],
    });
    return google.drive({ version: 'v3', auth });
}

export async function uploadToDrive(fileName: string, fileContent: Buffer, folderName: string) {
    try {
        const drive = await getDriveClient();

        // 1. Find or create the root CareerPilot folder
        let rootFolderId: string | undefined;
        const rootSearch = await drive.files.list({
            q: `name = 'CareerPilot_Applications' and mimeType = 'application/vnd.google-apps.folder' and trashed = false`,
            fields: 'files(id)',
        });

        if (rootSearch.data.files && rootSearch.data.files.length > 0) {
            rootFolderId = rootSearch.data.files[0].id;
        } else {
            const rootFolder = await drive.files.create({
                requestBody: {
                    name: 'CareerPilot_Applications',
                    mimeType: 'application/vnd.google-apps.folder',
                },
                fields: 'id',
            });
            rootFolderId = rootFolder.data.id;
        }

        // 2. Create a specific folder for this application
        const appFolder = await drive.files.create({
            requestBody: {
                name: folderName,
                mimeType: 'application/vnd.google-apps.folder',
                parents: [rootFolderId!],
            },
            fields: 'id',
        });
        const appFolderId = appFolder.data.id;

        // 3. Upload the file
        const fileMetadata = {
            name: fileName,
            parents: [appFolderId!],
        };
        const media = {
            mimeType: 'application/pdf',
            body: fs.createReadStream(fileName), // Assuming file is saved locally first
        };

        const file = await drive.files.create({
            requestBody: fileMetadata,
            media: media,
            fields: 'id, webViewLink',
        });

        return file.data.webViewLink;
    } catch (error) {
        console.error("Google Drive upload failed:", error);
        throw error;
    }
}
