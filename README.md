# Drone Swarm Control UI

A real-time strategy (RTS) style web interface for controlling a swarm of simulated drones. Built for the San Francisco 11/15 Hackathon (2025).

## Features

- **Real-time visualization**: View multiple drones on a 2D map with live position updates
- **Intuitive selection**: Click individual drones or drag to select multiple
- **Command interface**: Click anywhere on the map to move selected drones
- **Smooth simulation**: Backend continuously updates drone positions with physics-based movement

## Tech Stack

- **Backend**: FastAPI (Python) with async simulation loop
- **Frontend**: React + Vite with SVG rendering
- **Communication**: REST API with polling (250ms interval)

## Quick Start

### Prerequisites

- Python 3.8 or higher
- Node.js 16 or higher
- npm (comes with Node.js)

### Running the Application

Simply run the startup script:

```bash
python start.py
```

This will:
1. Create a Python virtual environment (isolated from your system Python/conda)
2. Install Python dependencies in the virtual environment
3. Install Node.js dependencies in `frontend/node_modules`
4. Start the backend server on `http://localhost:8000`
5. Start the frontend server on `http://localhost:5173`

**Note:** Dependencies are installed in a project-local virtual environment (`venv/`) and won't affect your system Python or conda environment.

The script works on both **Mac** and **Windows**.

### Manual Setup (Alternative)

If you prefer to run servers separately:

**Backend:**
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Usage

1. **Select drones**: 
   - Click on individual drones to select/deselect
   - Click and drag to create a selection box (selects all drones in the box)

2. **Move drones**:
   - Select one or more drones
   - Click anywhere on the map to set their destination
   - Drones will smoothly move to the target location

3. **Visual indicators**:
   - Green circles = unselected drones
   - Blue circles = selected drones
   - Orange dashed lines = movement targets and paths

## Project Structure

```
orion-hackathon/
├── backend/
│   ├── main.py              # FastAPI server with simulation
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # Main React component
│   │   ├── App.css         # Styles
│   │   ├── main.jsx        # Entry point
│   │   └── index.css       # Global styles
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── start.py                 # Cross-platform startup script
├── README.md
└── DESIGN.md               # Design document
```

## API Endpoints

- `GET /world` - Returns current state of all drones
- `POST /command` - Sends movement command to selected drones
  ```json
  {
    "drone_ids": ["drone_1", "drone_2"],
    "target_x": 500,
    "target_y": 300
  }
  ```

## Development Notes

- Backend simulation runs at 20Hz (50ms intervals)
- Frontend polls backend every 250ms
- World size: 1000x1000 pixels
- Drone speed: 50 pixels/second
- Initial setup: 12 drones in a 4x3 grid

## Future Extensions

See `DESIGN.md` for planned features:
- Autonomy levels
- Network degradation simulation
- Mission abstractions
- Replay system

## License

Built for hackathon purposes.

