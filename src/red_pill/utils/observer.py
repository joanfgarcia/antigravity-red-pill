import os
import subprocess

def notify_user(title: str, message: str, sound: bool = True):
    """
    Sends a system notification and optionally plays a subtle sound.
    """
    try:
        # 1. Desktop Notification
        subprocess.run(["notify-send", "-i", "security-high", title, message], check=False)
        
        # 2. Audio Cue (Sound of Silence v2 - Minimalist)
        if sound:
            # We use a simple beep or a system sound if available
            # aplay -q (quiet) + a frequency sweep or a sample
            # Since we are in the Bunker, we prefer a technical beep
            subprocess.run(["speaker-test", "-t", "sine", "-f", "880", "-l", "1", "-p", "50"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
    except Exception:
        pass # Never let notification failure stop the flow

if __name__ == "__main__":
    notify_user("Red Pill: Task Complete", "The heavy neural audit has finished successfully.")
