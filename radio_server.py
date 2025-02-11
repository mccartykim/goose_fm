#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#     "mcp",
#     "base64"
# ]
# ///

from mcp.server.fastmcp import FastMCP
import subprocess
import signal
import sys
import os
import time
import threading
import queue
import base64

# Global variables
current_process = None
current_frequency = None
audio_buffer = queue.Queue(maxsize=10000)  # Larger buffer for audio chunks
stop_event = threading.Event()

mcp = FastMCP("GooseFM")

def audio_capture_thread(rtl_process):
    """Capture audio from rtl_fm process into a thread-safe buffer."""
    global audio_buffer
    try:
        while not stop_event.is_set():
            chunk = rtl_process.stdout.read(4096)  # Read in 4KB chunks
            if not chunk:
                break
            
            # Encode chunk to base64 for easy transmission
            base64_chunk = base64.b64encode(chunk).decode('utf-8')
            
            try:
                # Non-blocking put with a timeout
                audio_buffer.put(base64_chunk, block=False)
            except queue.Full:
                # If buffer is full, remove oldest chunk
                try:
                    audio_buffer.get_nowait()
                except queue.Empty:
                    pass
                audio_buffer.put(base64_chunk, block=False)
    except Exception as e:
        print(f"Audio capture error: {e}")
    finally:
        rtl_process.stdout.close()

@mcp.resource('audio://radio/raw_audio')
def radio_audio_stream():
    """Provide base64 encoded audio stream."""
    chunk = ''
    while not stop_event.is_set():
        try:
            # Non-blocking get
            chunk = audio_buffer.get(timeout=0.1)
        except queue.Empty:
            # Yield empty string if no data
            chunk = ''
    
    return {
        'stream': chunk,
        'encoding': 'base64',
        'mime_type': 'audio/raw'
    }

@mcp.resource('radio://frequency')
def radio_frequency():
    """Provide current radio frequency."""
    return {
        'frequency': current_frequency
    }

def parse_frequency(freq: str) -> float:
    """Parse and validate the frequency string."""
    freq = freq.strip().upper()
    freq = freq.replace('MHZ', '').replace('M', '')
    
    try:
        freq_float = float(freq)
        if not (87.5 <= freq_float <= 108.0):
            raise ValueError("Frequency must be between 87.5 and 108.0 MHz")
        return freq_float
    except ValueError as e:
        if "must be between" in str(e):
            raise
        raise ValueError("Frequency must be a number between 87.5 and 108.0 MHz")

def cleanup_process():
    """Clean up radio processes and threads."""
    global current_process, current_frequency
    
    # Signal threads to stop
    stop_event.set()
    
    # Kill existing processes
    try:
        subprocess.run(["pkill", "-f", "rtl_fm"], check=False)
        subprocess.run(["pkill", "-f", "play"], check=False)
    except Exception as e:
        print(f"Process cleanup warning: {e}")
    
    # Reset global state
    current_process = None
    current_frequency = None
    
    # Clear audio buffer
    while not audio_buffer.empty():
        try:
            audio_buffer.get_nowait()
        except queue.Empty:
            break
    
    # Reset stop event
    stop_event.clear()

@mcp.tool()
def stop_radio() -> dict:
    """Stop the current radio stream."""
    cleanup_process()
    return {"status": "success", "message": "Radio stream stopped"}

@mcp.tool()
def tune_radio(frequency: str) -> dict:
    """Tune the radio to the specified frequency."""
    global current_process, current_frequency
    
    try:
        freq_float = parse_frequency(frequency)
    except ValueError as e:
        raise Exception(str(e))
    
    # Clean up any existing process
    cleanup_process()
    
    # Ensure clean start
    formatted_freq = f"{freq_float}M"
    
    try:
        # Simplified command with minimal parameters
        cmd = f"rtl_fm -f {formatted_freq} -s 240000 -r 48000 -l 30 -"
        
        # Start rtl_fm process
        rtl_process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # Ensures process is in its own group
        )
        
        # Start audio capture thread
        capture_thread = threading.Thread(
            target=audio_capture_thread, 
            args=(rtl_process,), 
            daemon=True
        )
        capture_thread.start()
        
        # Update global state
        current_process = rtl_process
        current_frequency = freq_float
        
        # Basic process check
        time.sleep(1)
        if rtl_process.poll() is not None:
            # Process terminated early, check for errors
            _, stderr = rtl_process.communicate()
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            cleanup_process()
            raise Exception(f"Failed to start radio: {error_msg}")
        
        return {
            "status": "success",
            "frequency": f"{freq_float} MHz",
            "formatted_command_frequency": formatted_freq
        }
    except Exception as e:
        cleanup_process()
        raise Exception(str(e))

if __name__ == "__main__":
    def signal_handler(sig, frame):
        cleanup_process()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    mcp.run()
