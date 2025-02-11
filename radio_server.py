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
stop_event = threading.Event()

mcp = FastMCP("GooseFM")

@mcp.resource('radio://station/frequency')
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
        play_cmd = "play -t s16 -r 48000 -e signed -b 16 -c 1 -"
        
        # Start rtl_fm process
        current_process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        # Verify process started successfully
        if current_process.poll() is not None:
            _, stderr = current_process.communicate()
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            cleanup_process()
            raise Exception(f"rtl_fm failed to start: {error_msg}")

        # Start play process
        play_process = subprocess.Popen(
            play_cmd.split(),
            stdin=current_process.stdout,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        if play_process.poll() is not None:
            _, stderr = play_process.communicate()
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            current_process.kill()
            cleanup_process()
            raise Exception(f"play failed to start: {error_msg}")
        # Give it a moment to start and check if it's still running
        time.sleep(0.5)
        if play_process.poll() is not None:
            # Process has already terminated, get error output
            _, stderr = play_process.communicate()
            error_msg = stderr.strip() if stderr else "Unknown error"
            raise Exception(f"Failed to start radio process: {error_msg}")
        
        # Start a non-blocking read of stderr
        error_output = ""
        try:
            error_output = current_process.stderr.readline()
        except:
            pass
            
        if error_output and "Found 1 device(s):" not in error_output and "Using device" not in error_output:
            cleanup_process()
            raise Exception(f"Failed to start radio: {error_msg}")
        
        current_frequency = formatted_freq
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
