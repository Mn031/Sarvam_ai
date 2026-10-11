import base64
import json
import os
from pathlib import Path
import requests
import streamlit as st
from dotenv import load_dotenv

# ---------------------------------------------------------
# Module 1: Environment & Config
# ---------------------------------------------------------
# Automatically locate and load .env from current and parent directories
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file)
else:
    load_dotenv()

# Streamlit Page Setup
st.set_page_config(
    page_title="TruthLens Indic",
    page_icon="🔍",
    layout="wide",
)

# API Key resolution: Environment variable preferred, sidebar fallback
env_api_key = os.getenv("SARVAM_API_KEY", "").strip()

with st.sidebar:
    st.header("⚙️ Configuration")
    if env_api_key:
        st.success("🔑 Sarvam API Key loaded from environment")
        sidebar_api_key = st.text_input(
            "Override Sarvam API Key (optional)",
            type="password",
            placeholder="Leave blank to use environment key",
        ).strip()
        active_api_key = sidebar_api_key if sidebar_api_key else env_api_key
    else:
        st.warning("⚠️ No API Key in environment.")
        active_api_key = st.text_input(
            "Sarvam API Key",
            type="password",
            placeholder="Enter your api-subscription-key",
            help="Get your key at https://dashboard.sarvam.ai",
        ).strip()

    st.markdown("---")
    st.markdown("### 📌 About TruthLens Indic")
    st.markdown(
        """
        Designed for regional misinformation (WhatsApp voice notes, forwarded clips).
        - **STT**: Sarvam Saaras (Speech-to-Text-Translate)
        - **Grounding**: DuckDuckGo Live Search
        - **Fact-Checker**: Sarvam-105b LLM
        - **TTS**: Sarvam Bulbul Native Voice
        """
    )


# ---------------------------------------------------------
# Module 2: Speech-to-Text-Translate Function
# ---------------------------------------------------------
def speech_to_text_translate(file_bytes: bytes, filename: str, api_key: str):
    """
    Transcribes regional audio/video and translates to English using Sarvam Saaras.
    Endpoint: https://api.sarvam.ai/speech-to-text-translate
    Model: saaras:v2.5
    """
    endpoint = "https://api.sarvam.ai/speech-to-text-translate"
    headers = {"api-subscription-key": api_key}

    ext = filename.split(".")[-1].lower() if "." in filename else "wav"
    mime_types = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "m4a": "audio/m4a",
        "mp4": "video/mp4",
    }
    mime_type = mime_types.get(ext, "audio/wav")

    files = {
        "file": (filename, file_bytes, mime_type),
    }
    data = {
        "model": "saaras:v2.5",
    }

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            files=files,
            data=data,
            timeout=90,
        )

        if response.status_code == 200:
            res_data = response.json()
            transcript = res_data.get("transcript", "")
            language_code = res_data.get("language_code", "hi-IN")
            return transcript, language_code
        else:
            st.error(
                f"STT API Error ({response.status_code}): {response.text}"
            )
            return None, "hi-IN"
    except Exception as e:
        st.error(f"Failed to connect to Sarvam STT service: {str(e)}")
        return None, "hi-IN"


# ---------------------------------------------------------
# Module 3: Web Search Grounding Function
# ---------------------------------------------------------
def ground_search(query: str) -> str:
    """
    Performs real-time web search for the claim using DuckDuckGo.
    Returns structured text snippets for top 3 sources.
    """
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            raw_results = ddgs.text(query, max_results=3)
            for i, r in enumerate(raw_results, start=1):
                title = r.get("title", "No Title")
                body = r.get("body", "No Snippet")
                url = r.get("href", "")
                results.append(
                    f"[Source {i}] Title: {title}\nURL: {url}\nSnippet: {body}"
                )

        if not results:
            return "No relevant real-time search results found."

        return "\n\n".join(results)
    except Exception as e:
        return f"Live web search was unavailable or timed out: {str(e)}"


# ---------------------------------------------------------
# Module 4: Fact-Checking LLM Call
# ---------------------------------------------------------
def fact_check_claim(claim_english: str, search_context: str, language_code: str, api_key: str):
    """
    Fact-checks claim using Sarvam 105b LLM with search grounding context.
    Returns parsed dictionary with verdict, confidence, and bilingual explanations.
    """
    endpoint = "https://api.sarvam.ai/v1/chat/completions"
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    system_prompt = f"""You are an expert fact-checker for Indian regional language content.
Analyze the user claim against the provided search context.

Respond STRICTLY with a valid JSON object matching this structure:
{{
    "verdict": "FALSE" | "TRUE" | "MISLEADING",
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "explanation_english": "A concise 2-sentence explanation in English.",
    "explanation_native": "The exact same concise 2-sentence explanation translated into the target language corresponding to BCP-47 code: {language_code}."
}}
Do not include markdown code block syntax (like ```json), commentary, or extra text."""

    user_content = f"Claim: {claim_english}\n\nSearch Context:\n{search_context}"

    payload = {
        "model": "sarvam-105b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            st.error(f"Chat Completion API Error ({response.status_code}): {response.text}")
            return None

        content = response.json()["choices"][0]["message"]["content"]
        # Response Cleaning
        clean_json_str = (
            content.replace("```json", "")
            .replace("```", "")
            .strip()
        )
        return json.loads(clean_json_str)
    except json.JSONDecodeError:
        # Fallback in case response had surrounding text
        st.warning("Parsing JSON response with heuristic extraction...")
        try:
            start_idx = clean_json_str.find("{")
            end_idx = clean_json_str.rfind("}")
            if start_idx != -1 and end_idx != -1:
                return json.loads(clean_json_str[start_idx : end_idx + 1])
        except Exception:
            pass
        st.error(f"Failed to parse LLM verdict response: {clean_json_str}")
        return None
    except Exception as e:
        st.error(f"Chat completion failed: {str(e)}")
        return None


# ---------------------------------------------------------
# Module 5: Text-to-Speech Conversion
# ---------------------------------------------------------
def text_to_speech(text: str, language_code: str, api_key: str):
    """
    Converts native explanation text into speech using Sarvam Bulbul.
    Returns decoded WAV audio bytes.
    """
    endpoint = "https://api.sarvam.ai/text-to-speech"
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    # Primary payload using bulbul:v1
    primary_payload = {
        "inputs": [text],
        "target_language_code": language_code,
        "speaker": "meera",
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 8000,
        "enable_preprocessing": True,
        "model": "bulbul:v1",
    }

    try:
        response = requests.post(endpoint, headers=headers, json=primary_payload, timeout=45)

        # Fallback to bulbul:v4-flash if primary returns non-200
        if response.status_code != 200:
            fallback_payload = {
                "text": text,
                "language_code": language_code,
                "speaker": "shubh_enhi_ads",
                "model": "bulbul:v4-flash",
            }
            response = requests.post(endpoint, headers=headers, json=fallback_payload, timeout=45)

        if response.status_code == 200:
            audios = response.json().get("audios", [])
            if audios:
                return base64.b64decode(audios[0])
            else:
                st.warning("TTS API succeeded but returned an empty audios list.")
                return None
        else:
            st.error(f"TTS API Error ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"TTS request failed: {str(e)}")
        return None


# ---------------------------------------------------------
# Module 6: Streamlit User Experience & Workflow
# ---------------------------------------------------------
st.title("🔍 TruthLens Indic")
st.caption("AI-Powered Regional Audio Fact-Checker for WhatsApp Viral Claims.")

st.markdown(
    """
    Upload a regional language audio clip, WhatsApp voice note, or video snippet.
    TruthLens will translate the claim, verify it against live web intelligence, and return
    a verdict along with an audio debunking explanation in the speaker's native tongue.
    """
)

uploaded_file = st.file_uploader(
    "Upload Regional Audio or Video",
    type=["wav", "mp3", "m4a", "mp4"],
    help="Supports WAV, MP3, M4A audio files and MP4 video clips",
)

if uploaded_file:
    # Quick audio preview if audio file
    file_ext = uploaded_file.name.split(".")[-1].lower()
    if file_ext in ["wav", "mp3", "m4a"]:
        st.audio(uploaded_file, format=f"audio/{file_ext}")
    elif file_ext == "mp4":
        st.video(uploaded_file)

execute_btn = st.button("🚀 Fact-Check Claim", type="primary", use_container_width=True)

if execute_btn:
    if not active_api_key:
        st.error("❌ Please provide a Sarvam API Key in the sidebar or via .env file to proceed.")
        st.stop()

    if not uploaded_file:
        st.warning("⚠️ Please upload an audio or video file first.")
        st.stop()

    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name

    with st.status("Analyzing clip...", expanded=True) as status_box:
        # Step 1: STT Translation
        st.write("🔄 **Step 1:** Transcribing & Translating Audio with Sarvam Saaras...")
        transcript, lang_code = speech_to_text_translate(file_bytes, filename, active_api_key)

        if not transcript:
            status_box.update(label="❌ Failed during Audio Transcription", state="error", expanded=True)
            st.stop()

        st.info(f"Detected Language: **{lang_code}** | English Translation: *\"{transcript}\"*")

        # Step 2: Grounding Search
        st.write("🌐 **Step 2:** Fetching Grounding Search Results...")
        search_context = ground_search(transcript)

        # Step 3: LLM Fact-Checking
        st.write("🤖 **Step 3:** Evaluating Factuality with Sarvam Chat AI...")
        fact_check_result = fact_check_claim(transcript, search_context, lang_code, active_api_key)

        if not fact_check_result:
            status_box.update(label="❌ Failed during LLM Fact-Checking", state="error", expanded=True)
            st.stop()

        verdict = str(fact_check_result.get("verdict", "MISLEADING")).upper()
        confidence = str(fact_check_result.get("confidence", "MEDIUM")).upper()
        explanation_en = fact_check_result.get("explanation_english", "")
        explanation_native = fact_check_result.get("explanation_native", "")

        # Step 4: Text to Speech
        st.write("🔊 **Step 4:** Generating Audio Explanation with Sarvam Bulbul...")
        audio_tts_bytes = text_to_speech(explanation_native, lang_code, active_api_key)

        status_box.update(label="✅ Analysis Complete!", state="complete", expanded=False)

    # ---------------------------------------------------------
    # Output Display
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("📊 Fact-Check Report")

    # Verdict Callout Badge
    if "FALSE" in verdict:
        st.error(f"❌ VERDICT: FALSE  (Confidence: {confidence})")
    elif "TRUE" in verdict:
        st.success(f"✅ VERDICT: TRUE  (Confidence: {confidence})")
    else:
        st.warning(f"⚠️ VERDICT: MISLEADING  (Confidence: {confidence})")

    # Explanation Cards (Side-by-side)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🇬🇧 English Explanation")
        st.markdown(
            f"""
            <div style="background-color: rgba(128, 128, 128, 0.1); padding: 15px; border-radius: 8px; border-left: 4px solid #4CAF50;">
                <p style="margin: 0; font-size: 1.05rem;">{explanation_en}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(f"### 🇮🇳 Native Explanation ({lang_code})")
        st.markdown(
            f"""
            <div style="background-color: rgba(128, 128, 128, 0.1); padding: 15px; border-radius: 8px; border-left: 4px solid #2196F3;">
                <p style="margin: 0; font-size: 1.05rem;">{explanation_native}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Native Voice Player
    st.markdown("### 🎙️ Listen to Explanation in Native Language")
    if audio_tts_bytes:
        st.audio(audio_tts_bytes, format="audio/wav")
    else:
        st.info("Audio explanation could not be synthesized. Please refer to text explanations above.")

    # Grounding Sources & Raw Transcript in expander
    with st.expander("🔎 View Grounding Details & Sources"):
        st.markdown(f"**Translated Audio Claim:**\n> {transcript}")
        st.markdown("**Web Grounding Snippets Used:**")
        st.text(search_context)
