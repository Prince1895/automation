import axios from 'axios';
import dotenv from 'dotenv';

dotenv.config();

const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";

export async function analyzeJob(resumeText, jobDescription) {
    const prompt = `
    You are an expert Technical Recruiter.
    Analyze the following Resume and Job Description.

    RESUME:
    ${resumeText}

    JOB DESCRIPTION:
    ${jobDescription}

    Provide the output in STRICT JSON format:
    {
      "match_score": (0-100),
      "reasoning": "Short explanation of why it matches or doesn't",
      "missing_keywords": ["keyword1", "keyword2"],
      "tailored_bullet_points": [
        "Modified bullet point 1 to match JD",
        "Modified bullet point 2 to match JD"
      ],
      "suggested_cover_letter_hook": "A professional opening sentence tailored to this company",
      "cover_letter": "A full, high-conversion, professional cover letter tailored to the JD and Resume",
      "should_apply": (true/false)
    }
    `;

    try {
        const response = await axios.post(OPENROUTER_URL, {
            model: "meta-llama/llama-3-8b-instruct:free",
            messages: [{ role: "user", content: prompt }]
        }, {
            headers: {
                "Authorization": `Bearer ${process.env.OPENROUTER_API_KEY}`,
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "Career Pilot"
            }
        });

        let content = response.data.choices[0].message.content;
        if (content.includes("```json")) {
            content = content.split("```json")[1].split("```")[0].trim();
        } else if (content.includes("```")) {
            content = content.split("```")[1].split("```")[0].trim();
        }

        return JSON.parse(content);
    } catch (error) {
        console.error("Error analyzing job:", error);
        throw error;
    }
}
