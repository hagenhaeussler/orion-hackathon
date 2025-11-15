"""
FastAPI backend for drone swarm simulation.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import asyncio
from datetime import datetime
import math

app = FastAPI(title="Drone Swarm API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class Drone(BaseModel):
    id: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    mode: str = "idle"  # idle, moving
    target_x: Optional[float] = None
    target_y: Optional[float] = None

class WorldState(BaseModel):
    drones: List[Drone]
    timestamp: float

class Command(BaseModel):
    drone_ids: List[str]
    target_x: float
    target_y: float

# In-memory world state
world = {
    "drones": {},
    "last_update": datetime.now().timestamp()
}

# Simulation parameters
DRONE_SPEED = 50.0  # pixels per second
WORLD_WIDTH = 1000
WORLD_HEIGHT = 1000
SIMULATION_DT = 0.05  # 50ms update interval

def init_drones():
    """Initialize drones in a grid pattern."""
    num_drones = 12
    cols = 4
    spacing = 80
    start_x = 200
    start_y = 200
    
    for i in range(num_drones):
        row = i // cols
        col = i % cols
        drone_id = f"drone_{i+1}"
        world["drones"][drone_id] = Drone(
            id=drone_id,
            x=start_x + col * spacing,
            y=start_y + row * spacing,
            vx=0.0,
            vy=0.0,
            mode="idle"
        )

def update_drone(drone: Drone, dt: float) -> Drone:
    """Update drone position based on current velocity and target."""
    if drone.mode == "moving" and drone.target_x is not None and drone.target_y is not None:
        # Calculate distance to target
        dx = drone.target_x - drone.x
        dy = drone.target_y - drone.y
        distance = math.sqrt(dx * dx + dy * dy)
        
        if distance < 5.0:  # Close enough to target
            # Arrived at target
            drone.x = drone.target_x
            drone.y = drone.target_y
            drone.vx = 0.0
            drone.vy = 0.0
            drone.mode = "idle"
            drone.target_x = None
            drone.target_y = None
        else:
            # Move towards target
            # Normalize direction
            if distance > 0:
                direction_x = dx / distance
                direction_y = dy / distance
            else:
                direction_x = 0
                direction_y = 0
            
            # Set velocity
            drone.vx = direction_x * DRONE_SPEED
            drone.vy = direction_y * DRONE_SPEED
            
            # Update position
            drone.x += drone.vx * dt
            drone.y += drone.vy * dt
            
            # Clamp to world bounds
            drone.x = max(0, min(WORLD_WIDTH, drone.x))
            drone.y = max(0, min(WORLD_HEIGHT, drone.y))
    
    return drone

async def simulation_loop():
    """Background task that updates drone positions."""
    while True:
        current_time = datetime.now().timestamp()
        dt = min(SIMULATION_DT, current_time - world["last_update"])
        world["last_update"] = current_time
        
        # Update all drones
        for drone_id, drone in world["drones"].items():
            world["drones"][drone_id] = update_drone(drone, dt)
        
        await asyncio.sleep(SIMULATION_DT)

@app.on_event("startup")
async def startup_event():
    """Initialize drones and start simulation loop."""
    init_drones()
    asyncio.create_task(simulation_loop())

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Drone Swarm API"}

@app.get("/world", response_model=WorldState)
async def get_world():
    """Get current world state with all drones."""
    return WorldState(
        drones=list(world["drones"].values()),
        timestamp=world["last_update"]
    )

@app.post("/command")
async def send_command(command: Command):
    """Send a command to move selected drones to a target location."""
    updated_count = 0
    for drone_id in command.drone_ids:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            drone.target_x = command.target_x
            drone.target_y = command.target_y
            drone.mode = "moving"
            world["drones"][drone_id] = drone
            updated_count += 1
    
    return {
        "status": "ok",
        "updated_drones": updated_count,
        "target": {"x": command.target_x, "y": command.target_y}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

