import os
from dotenv import load_dotenv
from google.cloud import texttospeech
from google.cloud import translate_v2 as translate  # This works after installing the package
from google.oauth2 import service_account

load_dotenv()

def english_to_kannada_tts(text, output_file="output_kannada.mp3"):
    # Load credentials
    creds_path = os.getenv("GOOGLE_TTS")
    if not creds_path or not os.path.exists(creds_path):
        raise Exception("GOOGLE_TTS path not found or file doesn't exist in .env")

    credentials = service_account.Credentials.from_service_account_file(creds_path)

    # Step 1: Translate English → Kannada
    translate_client = translate.Client(credentials=credentials)
    result = translate_client.translate(text, target_language="kn")
    kannada_text = result["translatedText"]
    print(f"Translated to Kannada: {kannada_text}")

    # Step 2: Text-to-Speech in Kannada
    tts_client = texttospeech.TextToSpeechClient(credentials=credentials)

    synthesis_input = texttospeech.SynthesisInput(text=kannada_text)

    voice = texttospeech.VoiceSelectionParams(
        language_code="kn-IN",
        name="kn-IN-Chirp3-HD-Achernar"  # Best quality Kannada voice
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )

    # Save the audio file
    with open(output_file, "wb") as out:
        out.write(response.audio_content)

    print(f"Success: Kannada audio saved as {output_file}")
    return output_file


# ---------------- RUN ----------------
if __name__ == "__main__":
    english_text = """
Quadrant Leave Policy Overview:
- Objective: Quadrant encourages employee well-being and supports taking leaves for personal time off to ensure employees are at their best when at work.
- Applicability: This policy applies to all permanent employees of the company.
- Leave Year: The leave year is based on the calendar year.

Types of Leaves:
1. Casual Leave (CL):
   - All permanent employees are entitled to 20 days of leave annually (pro-rated from the date of joining).
   - During the probation period, employees will be eligible for 1 leave per month.
   - Leaves are credited on a quarterly basis (5 per quarter) after the probation period.
   - At the end of the year, only 8 leaves can be carried forward to the next year.

2. Compensatory Off (CO):
   - Employees may be entitled to Comp Off if they work on national, non-working, or festival holidays, subject to prior agreement with their reporting manager.

3. Maternity Leave (ML):
   - Female employees are entitled to 8 weeks of maternity leave after working for a minimum of 80 days in the last 12 months.

Other Rules:
- Employees must communicate leave details to their respective Reporting Managers via email and get approval in writing.
- All leaves must be applied in the designated system (GreytHR) and approved before payroll cut-off dates.
- In case of non-regularization, leave will be considered as Leave Without Pay (LOP).

If you have any further questions or need more details, feel free to ask!
"""

    english_to_kannada_tts(english_text)
