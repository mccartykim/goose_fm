#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#     "mcp",
# ]
# ///

from mcp.server.fastmcp import FastMCP
import subprocess
import signal
import sys
import os
import time

# Global variable to store the current process
current_process = None

mcp = FastMCP("GooseFM")

def parse_frequency(freq: str) -> float:
    """Parse and validate the frequency string.
    
    Accepts formats:
    - Plain number: "95.5", "98.6"
    - With M suffix: "95.5M", "98.6M"
    - With MHz suffix: "95.5MHz", "98.6MHz"
    
    Returns the frequency as a float if valid, raises ValueError if invalid.
    """
    # Remove whitespace and convert to uppercase
    freq = freq.strip().upper()
    
    # Remove M or MHz suffix if present
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

def kill_existing_radio_processes():
    """Kill any existing rtl_fm and play processes."""
    try:
        # Kill rtl_fm processes
        subprocess.run(["pkill", "-f", "rtl_fm"], check=False)
        # Kill sox play processes
        subprocess.run(["pkill", "-f", "play -r 48000"], check=False)
        # Small delay to ensure processes are cleaned up
        time.sleep(0.5)
    except Exception as e:
        print(f"Warning: Error while killing existing processes: {e}")

def cleanup_process():
    """Clean up the current radio process if it exists."""
    global current_process
    if current_process:
        try:
            # Send SIGTERM to the process group
            pgid = os.getpgid(current_process.pid)
            os.killpg(pgid, signal.SIGTERM)
        except:
            pass
        current_process = None
    # Also make sure to kill any lingering processes
    kill_existing_radio_processes()

@mcp.tool()
def stop_radio() -> dict:
    """Stop the current radio stream."""
    cleanup_process()
    return {"status": "success", "message": "Radio stream stopped"}

@mcp.tool()
def tune_radio(frequency: str) -> dict:
    """Tune the radio to the specified frequency.
    
    The frequency can be specified in the following formats:
    - Plain number: "95.5", "98.6"
    - With M suffix: "95.5M", "98.6M"
    - With MHz suffix: "95.5MHz", "98.6MHz"
    
    The frequency must be between 87.5 and 108.0 MHz.
    """
    global current_process
    
    try:
        freq_float = parse_frequency(frequency)
    except ValueError as e:
        raise Exception(str(e))
    
    # Clean up any existing process
    cleanup_process()
    # Double-check for any lingering processes
    kill_existing_radio_processes()
    
    # Always format frequency with M suffix for rtl_fm
    formatted_freq = f"{freq_float}M"
    
    try:
        # Create the command - add -A fast AGC mode and gain setting
        cmd = f"/bin/rtl_fm -f {formatted_freq} -s 240000 -r 48000 -l 30 -A fast -g 49.6 - | /bin/play -r 48000 -t s16 -L -c 1 - --buffer 2048"
        
        # Start the new process with error output captured
        current_process = subprocess.Popen(
            cmd,
            shell=True,
            preexec_fn=os.setsid,  # Create new process group
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Give it a moment to start and check if it's still running
        time.sleep(0.5)
        if current_process.poll() is not None:
            # Process has already terminated, get error output
            _, stderr = current_process.communicate()
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
            raise Exception(f"Radio process reported error: {error_output}")
            
        return {
            "status": "success",
            "frequency": f"{freq_float} MHz",
            "formatted_command_frequency": formatted_freq
        }
    except Exception as e:
        cleanup_process()  # Clean up in case of failure
        raise Exception(str(e))

@mcp.tool()
def tune_radio_tool(frequency: str) -> dict:
    """Tune the radio to a specific frequency as a tool.
    Accepts the same frequency formats as the resource endpoint."""
    return tune_radio(frequency)

@mcp.tool()
def stop_radio_tool() -> dict:
    """Stop the radio stream as a tool."""
    return stop_radio()

@mcp.prompt()
def tune_radio_prompt(frequency: str) -> str:
    """Create a prompt to tune the radio to a specific frequency."""
    return f"Please tune the radio to {frequency} MHz"

@mcp.prompt()
def stop_radio_prompt() -> str:
    """Create a prompt to stop the radio."""
    return "Please stop the radio stream"

if __name__ == "__main__":
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        cleanup_process()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Clean up any existing processes on startup
    kill_existing_radio_processes()
    
    # Run the server - FastMCP will handle this
    mcp.run()
