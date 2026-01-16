# dont-forget-your-breaks

A cross-platform desktop application that reminds you to take regular breaks during work sessions. Built with Python and Tkinter.

## Features

- **Multiple break types**: Configure different break patterns (e.g., micro-breaks and normal breaks)
- **Customizable intervals**: Set break frequency in seconds, minutes, or hours
- **Configurable duration**: Define how long each break should last
- **Audio notifications**: Choose from system sounds for break start/end alerts
- **Loop end sound**: Optionally loop the end sound until you acknowledge the break
- **Auto-dismiss**: Automatically close the break popup or require manual acknowledgment
- **Pause/Resume**: Pause all timers without resetting them
- **Test breaks**: Preview any break configuration before starting

## Default Configuration

| Break Type   | Interval   | Duration   | Start Sound | End Sound  |
|-------------|------------|------------|-------------|------------|
| Micro Break | 25 minutes | 5 seconds  | Ping        | Glass      |
| Normal Break| 50 minutes | 10 minutes | Glass       | Submarine  |

## Requirements

- Python 3.x
- Tkinter (included with Python on most systems)

### Platform Support

- **macOS**: Full sound support using system sounds
- **Windows**: Basic beep notification
- **Linux**: Terminal bell fallback

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/dont-forget-your-breaks.git
   cd dont-forget-your-breaks
   ```

2. Run the application:
   ```bash
   python launch.py
   ```

## Building the macOS App

To build a standalone macOS application:

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```

2. Build using the spec file:
   ```bash
   pyinstaller "Dont Forget Your Breaks.spec"
   ```

3. The app will be available in `dist/Dont Forget Your Breaks.app`

## Usage

1. **Start**: Click "Start" to begin tracking break intervals
2. **Pause/Resume**: Pause timers without resetting (useful for meetings)
3. **Stop**: Stop and reset all timers
4. **Configure**: Adjust interval, duration, and sounds for each break type
5. **Test**: Use "Test Break" to preview a break popup

## License

MIT License
