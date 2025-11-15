# CLAUDE.md - AI Assistant Guide for Drone Swarm Control UI

## Project Overview

This is a **real-time strategy (RTS) style web interface** for controlling a swarm of simulated drones, built for the San Francisco 11/15 Hackathon (2025). The project demonstrates human-robot teaming concepts through an intuitive web-based control interface.

### Core Capabilities
- Real-time visualization of multiple drones on a 2D map
- Individual and group selection (click or drag-select)
- Command-based movement controls
- Physics-based drone simulation with smooth movement
- Live position updates via REST API polling

### Tech Stack
- **Backend**: FastAPI (Python) with async simulation loop
- **Frontend**: React 18 + Vite 5 with SVG rendering
- **Communication**: REST API with 250ms polling interval
- **Deployment**: Local development (no production deployment)

---

## Architecture

### System Design
```
┌─────────────────┐         HTTP REST         ┌──────────────────┐
│   React Frontend│ ◄────────────────────────► │  FastAPI Backend │
│   (Port 5173)   │   GET /world (250ms poll)  │   (Port 8000)    │
│                 │   POST /command            │                  │
└─────────────────┘                            └──────────────────┘
                                                        │
                                                        ▼
                                                ┌──────────────────┐
                                                │ Simulation Loop  │
                                                │   (50ms / 20Hz)  │
                                                └──────────────────┘
```

### Key Principles
1. **Separation of Concerns**: Frontend handles UI/UX, backend handles simulation physics
2. **Stateless Frontend**: All state lives in backend; frontend is purely presentational
3. **Polling Architecture**: Frontend polls backend every 250ms (simpler than WebSockets for MVP)
4. **Real-time Simulation**: Backend continuously updates drone positions at 20Hz

---

## Project Structure

```
orion-hackathon/
├── backend/
│   ├── main.py              # FastAPI server + simulation engine (171 lines)
│   └── requirements.txt     # Python dependencies (fastapi, uvicorn, pydantic)
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component (259 lines)
│   │   ├── App.css          # Component styles
│   │   ├── main.jsx         # React entry point
│   │   └── index.css        # Global styles
│   ├── index.html           # HTML template
│   ├── package.json         # Node dependencies (React 18, Vite 5)
│   └── vite.config.js       # Vite configuration
├── start.py                 # Cross-platform startup script (Mac + Windows)
├── README.md                # User-facing documentation
├── DESIGN.md                # Design document and project rationale
├── CLAUDE.md                # This file - AI assistant guide
├── .gitignore               # Git ignore patterns
└── venv/                    # Python virtual environment (gitignored)
```

---

## Backend Details

### File: `backend/main.py`

**Core Data Models** (Pydantic):
```python
Drone(id, x, y, vx, vy, mode, target_x, target_y)
WorldState(drones: List[Drone], timestamp: float)
Command(drone_ids: List[str], target_x: float, target_y: float)
```

**Simulation Constants**:
- `DRONE_SPEED`: 50 pixels/second
- `WORLD_WIDTH` / `WORLD_HEIGHT`: 1000x1000 pixels
- `SIMULATION_DT`: 0.05 seconds (50ms updates, 20Hz)
- Initial setup: 12 drones in a 4x3 grid (80px spacing)

**Key Functions**:
- `init_drones()`: Creates 12 drones in grid pattern starting at (200, 200)
- `update_drone(drone, dt)`: Physics update - moves drone toward target, handles arrival
- `simulation_loop()`: Async background task running at 20Hz
- Movement logic: Normalize direction vector, apply constant speed, stop within 5px of target

**API Endpoints**:
- `GET /`: Health check
- `GET /world`: Returns WorldState with all drones and timestamp
- `POST /command`: Accepts Command, updates drone targets, returns status

**CORS Configuration**:
- Allows origins: `http://localhost:5173`, `http://localhost:3000`
- All methods and headers allowed (development mode)

---

## Frontend Details

### File: `frontend/src/App.jsx`

**State Management**:
```javascript
drones: []                    // Array of drone objects from backend
selectedDrones: Set           // Set of selected drone IDs
isDragging: boolean           // Selection box drag state
dragStart/dragEnd: {x, y}     // World coordinates for selection box
```

**Key Features**:
1. **Polling Loop**: `useEffect` fetches `/world` every 250ms
2. **Coordinate Conversion**: `screenToWorld()` converts mouse events to world coordinates
3. **Selection Modes**:
   - Click individual drone to toggle selection
   - Drag to create selection box (selects all drones inside)
   - Shift+drag to add to existing selection
4. **Command Sending**: Click map with selected drones → POST to `/command`
5. **Visual Indicators**:
   - Green circles (#00ff88): Unselected drones
   - Blue circles (#00aaff): Selected drones (larger, white stroke)
   - Orange dashed lines: Movement targets and paths
   - Grid background: 50px grid pattern

**Performance Considerations**:
- Uses `useCallback` to memoize event handlers
- Selection box only renders during drag
- SVG viewBox for resolution-independent rendering

---

## Development Workflow

### First-Time Setup
```bash
python start.py
```
This script automatically:
1. Creates Python virtual environment in `venv/`
2. Installs Python dependencies in isolated venv
3. Installs Node.js dependencies in `frontend/node_modules`
4. Starts backend on `http://localhost:8000`
5. Starts frontend on `http://localhost:5173`

**Important**: Dependencies are isolated in project-local `venv/`, not system Python or conda.

### Manual Server Management

**Backend only**:
```bash
cd backend
source ../venv/bin/activate  # On Mac/Linux
# ../venv/Scripts/activate    # On Windows
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Frontend only**:
```bash
cd frontend
npm run dev
```

**Frontend build** (production):
```bash
cd frontend
npm run build  # Output to frontend/dist/
```

---

## Code Conventions

### Python (Backend)
- **Style**: PEP 8 conventions
- **Type Hints**: Use Pydantic models for API contracts
- **Async/Await**: All FastAPI endpoints are async
- **Docstrings**: Triple-quoted docstrings for functions
- **Naming**: snake_case for functions/variables, PascalCase for classes

### JavaScript (Frontend)
- **Style**: Modern ES6+ with React hooks
- **Components**: Functional components only (no class components)
- **Hooks**: Use `useState`, `useEffect`, `useRef`, `useCallback`
- **Naming**: camelCase for functions/variables, PascalCase for components
- **Event Handlers**: Prefix with `handle` (e.g., `handleMapClick`)

### File Organization
- Keep all backend code in `backend/`
- Keep all frontend code in `frontend/src/`
- No nested subdirectories (flat structure for MVP)
- Configuration files at project/folder root

---

## Common Tasks

### Adding a New API Endpoint

1. **Define Pydantic model** (if needed) in `backend/main.py`
2. **Add endpoint handler**:
   ```python
   @app.get("/my-endpoint")
   async def my_handler():
       return {"data": "value"}
   ```
3. **Update frontend** to call endpoint in `App.jsx`

### Adding a New Drone Property

1. **Update `Drone` model** in `backend/main.py`:
   ```python
   class Drone(BaseModel):
       # ... existing fields
       my_property: str = "default"
   ```
2. **Update `init_drones()`** to initialize the property
3. **Update `update_drone()`** if property affects simulation
4. **Update frontend** to display/use the property

### Changing Simulation Parameters

Edit constants in `backend/main.py`:
- `DRONE_SPEED`: Movement speed (pixels/second)
- `WORLD_WIDTH/HEIGHT`: Map dimensions
- `SIMULATION_DT`: Simulation timestep
- Modify grid in `init_drones()`: `num_drones`, `cols`, `spacing`, `start_x/y`

### Changing UI Styling

- **Colors/sizes**: Edit `frontend/src/App.jsx` inline styles or SVG attributes
- **Layout**: Edit `frontend/src/App.css`
- **Global styles**: Edit `frontend/src/index.css`

---

## Testing & Debugging

### Backend Testing
```bash
# Manual endpoint testing
curl http://localhost:8000/world
curl -X POST http://localhost:8000/command \
  -H "Content-Type: application/json" \
  -d '{"drone_ids": ["drone_1"], "target_x": 500, "target_y": 500}'

# Check logs
# Backend prints to terminal where start.py was run
```

### Frontend Testing
- Open browser DevTools (F12)
- Check Console for errors
- Use React DevTools browser extension
- Network tab shows polling requests every 250ms

### Common Issues

**"Failed to fetch world state"**:
- Check backend is running on port 8000
- Check CORS configuration in `backend/main.py`
- Verify `API_BASE` in `App.jsx` matches backend URL

**Drones not moving**:
- Check simulation loop is running (should see position updates)
- Verify command reaches backend (check terminal logs)
- Ensure drone IDs match between frontend and backend

**Selection not working**:
- Check event handlers are firing (add console.logs)
- Verify coordinate conversion (`screenToWorld()`)
- Check `selectedDrones` Set is updating

---

## API Reference

### GET `/world`
**Response**: `WorldState`
```json
{
  "drones": [
    {
      "id": "drone_1",
      "x": 200.0,
      "y": 200.0,
      "vx": 0.0,
      "vy": 0.0,
      "mode": "idle",
      "target_x": null,
      "target_y": null
    }
  ],
  "timestamp": 1700000000.123
}
```

### POST `/command`
**Request**: `Command`
```json
{
  "drone_ids": ["drone_1", "drone_2"],
  "target_x": 500.0,
  "target_y": 300.0
}
```

**Response**:
```json
{
  "status": "ok",
  "updated_drones": 2,
  "target": {"x": 500.0, "y": 300.0}
}
```

---

## Important Constraints

### Performance
- **Backend Simulation**: 20Hz (50ms) is sufficient for smooth movement
- **Frontend Polling**: 250ms balances responsiveness and network load
- **Scaling**: Current architecture supports ~100 drones before performance degrades

### Browser Compatibility
- Requires modern browser with ES6+ support
- SVG rendering required (all modern browsers)
- No Internet Explorer support

### Network Assumptions
- Assumes localhost deployment (no authentication/security)
- No error recovery for network failures (MVP simplification)
- No offline mode or state persistence

---

## Future Extensions (See DESIGN.md)

These are **not implemented** but documented as potential enhancements:

1. **Autonomy Levels**: Drones make decisions vs. wait for commands
2. **Network Degradation**: Simulate latency, packet loss
3. **Mission Abstractions**: High-level commands (patrol, search, formation)
4. **Replay System**: Record and playback simulation sessions
5. **WebSocket Communication**: Replace polling for lower latency
6. **Multiple Operators**: Multi-user control interface
7. **3D Visualization**: Altitude and 3D movement

---

## Working with AI Assistants

### When Making Changes

1. **Read before editing**: Always read the full file before making changes
2. **Preserve structure**: Maintain the separation between backend/frontend
3. **Test endpoints**: After backend changes, manually test with curl
4. **Check simulation**: Ensure simulation loop still runs after modifications
5. **Verify CORS**: Don't break CORS settings or frontend won't connect

### Common Requests

**"Add a new feature"**:
- First determine: Backend change? Frontend change? Both?
- Update data models if adding new state
- Update both GET `/world` and frontend rendering if changing drone display

**"Fix a bug"**:
- Identify layer: Simulation logic? API? Frontend rendering? Event handling?
- Check relevant section in this guide
- Test with curl (backend) or console.log (frontend)

**"Improve performance"**:
- Backend: Optimize `update_drone()` loop
- Frontend: Add memoization, reduce re-renders
- Network: Reduce polling frequency or switch to WebSockets

**"Change simulation behavior"**:
- All physics logic is in `update_drone()` function
- Adjust constants at top of `backend/main.py`
- Movement uses normalized direction vectors * constant speed

---

## Git Workflow

### Current Branch
Working on: `claude/claude-md-mi0ovydwt0b20afe-016ryBw2uhEujSt1F7siFHeh`

### Commit Guidelines
- Clear, descriptive commit messages
- Test changes before committing
- Don't commit `venv/`, `node_modules/`, or build artifacts (see `.gitignore`)

### Branching
- Development happens on feature branches starting with `claude/`
- Main branch is protected
- Push to designated feature branch for this session

---

## Quick Reference

### Key Files to Edit

| Task | Files to Modify |
|------|----------------|
| Add API endpoint | `backend/main.py` |
| Change simulation | `backend/main.py` (update_drone, constants) |
| Add drone property | `backend/main.py` (Drone model, init_drones) |
| Change UI appearance | `frontend/src/App.jsx`, `App.css` |
| Add user interaction | `frontend/src/App.jsx` (event handlers) |
| Change polling rate | `frontend/src/App.jsx` (POLL_INTERVAL) |
| Update dependencies | `backend/requirements.txt`, `frontend/package.json` |

### Ports
- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs` (auto-generated by FastAPI)

### Startup Commands
- **Recommended**: `python start.py` (handles everything)
- **Backend only**: `cd backend && ../venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`
- **Frontend only**: `cd frontend && npm run dev`

---

## Additional Resources

- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **React Docs**: https://react.dev/
- **Vite Docs**: https://vitejs.dev/
- **Pydantic Docs**: https://docs.pydantic.dev/

---

**Last Updated**: 2025-11-15
**Project Status**: MVP complete, functional demo
**Hackathon**: San Francisco 11/15 Hackathon (2025)
