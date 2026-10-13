"""Text-to-speech for the re-speak feature: edge-tts first, gTTS as fallback."""
import asyncio


def speak(text, out_path, voice="en-US-AriaNeural", rate="-5%"):
    try:
        import edge_tts

        async def _go():
            await edge_tts.Communicate(text, voice, rate=rate).save(str(out_path))
        asyncio.run(_go())
        return "edge-tts"
    except Exception:
        from gtts import gTTS
        gTTS(text).save(str(out_path))
        return "gTTS"
