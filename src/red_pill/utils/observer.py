import os
import subprocess

def notify_user(title: str, message: str, sound: bool = True):
    """
    Sends a system notification and optionally plays a subtle sound.
    """
    try:
        # Tone Calibration: Soft, intuitive, sensory
        subprocess.run(["notify-send", "-i", "face-angel", title, f"Joan, {message}"], check=False)
        
        if sound:
            # A soft rising sweep (880Hz to 1100Hz) - Sensory notification
            # We use a shorter, more melodic pulse
            subprocess.run(["speaker-test", "-t", "sine", "-f", "980", "-l", "1"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            
    except Exception:
        pass # Never let notification failure stop the flow

if __name__ == "__main__":
    notify_user("Red Pill: Task Complete", "The heavy neural audit has finished successfully.")
