# DESIGN DOCUMENT

## Project: Supreme Commander–Style Drone Swarm UI
**Hackathon:** San Francisco 11/15 Hackathon (2025)  
**Team Members:** [Your Names]  
**Tech Stack:** React (frontend), FastAPI (backend), Python simulation loop

---

## 1. Context

### The Hackathon
We are participating in the San Francisco 11/15 Hackathon where teams rapidly prototype drone-related systems. The prompt includes multiple project options involving UAV autonomy, human–robot teaming, and real-time control interfaces.

### Prompt Option We Chose (#2)
> Design and prototype a web-based interface similar to real-time strategy (RTS) games that enables one operator to intuitively command and manage dozens of UAVs using standard input devices (keyboard/mouse/touchscreen). Explore which decisions should be made on the web app vs the UAV themselves, considering ease-of-use, reliability, network dependencies, and real-life constraints.

### Our Backgrounds
- Both developers are comfortable with **Python**, and have experience with Java, C, and JavaScript.
- One teammate has stronger engineering/architecture experience.
- The other teammate is comfortable writing frontend code with guidance.
- Neither of us are drone experts, but both have strong CS foundations.

We want a **working demo** we’re proud of.

---

## 2. Project Goal

Build a minimal but polished MVP of a real-time RTS-like drone control UI:

- Web UI shows multiple drones on a 2D map.
- User can select drones.
- User clicks somewhere → drones move there.
- Backend simulates drone positions.
- World updates in real time via polling.

This is a fully simulated project, aligned with Hackathon Option #2.

---

## 3. MVP Requirements

### Frontend (React + SVG)
- Display drones on a 2D map.
- Poll backend every ~250ms.
- Click/drag selection.
- Issue move commands through `POST /command`.

### Backend (FastAPI)
- In-memory world model:
  ```python
  Drone(id, x, y, vx, vy, mode)
  ```
- Simulation loop updates drone positions.
- `/world` returns full world state.
- `/command` updates drone targets.

### Repo Setup
- `backend/` + `frontend/`
- Start scripts
- README
- DESIGN.md

---

## 4. Optional Extensions

- Autonomy levels
- Network degradation simulation
- Mission abstractions
- Replay system

---

## 5. Architecture

```
frontend (React)
    → GET /world
    → POST /command
backend (FastAPI)
    → simulation loop
```

### GET `/world`
Returns drone list.

### POST `/command`
Assigns new target for drones.

---

## 6. Implementation Plan

### 1. Repo scaffolding
- Cursor generates initial files.
- Create FastAPI & Vite app.

### 2. Backend simulation
- Implement move logic.
- Implement command handling.

### 3. Frontend UI
- Render drones.
- Poll world.
- Input interactions.

### 4. Integration
- Verify movement end-to-end.

### 5. Stretch goals
If time remains.

---

End of design document.
