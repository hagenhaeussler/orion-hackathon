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
    mode: str = "idle"  # idle, moving, pattern
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    team: str = "friendly"  # friendly or enemy
    pattern: Optional[str] = None  # up_down, left_right, circular, None
    pattern_data: Optional[dict] = None  # Pattern-specific state
    last_x: Optional[float] = None  # Previous position for stuck detection
    last_y: Optional[float] = None
    stuck_frames: int = 0  # Number of frames without movement

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
ENEMY_SPEED = 40.0  # pixels per second for enemy drones
WORLD_WIDTH = 1000
WORLD_HEIGHT = 1000
SIMULATION_DT = 0.02  # 20ms update interval (50Hz for smooth physics)
DRONE_VISUAL_RADIUS = 10.0  # Visual radius of drones (matches frontend circle)
DRONE_STROKE_WIDTH = 3.0  # Maximum stroke width (selected drones have strokeWidth=3, unselected=2)
# In SVG, stroke is centered on the path, so outer edge is at radius + strokeWidth/2
# But we'll use radius + strokeWidth to ensure we catch all collisions including the full stroke
DRONE_HITBOX_RADIUS = DRONE_VISUAL_RADIUS + (DRONE_STROKE_WIDTH / 2.0)  # Total hitbox includes outer stroke edge
DRONE_RADIUS = DRONE_HITBOX_RADIUS  # Use hitbox radius for collision detection
SEPARATION_DISTANCE = DRONE_HITBOX_RADIUS * 2.2  # Minimum distance between friendly drones (slightly more than touching)
SEPARATION_FORCE = 300.0  # Force applied for separation (increased for better separation)
STUCK_THRESHOLD = 0.5  # Movement threshold to consider drone as having moved (pixels)
STUCK_FRAMES_TO_ARRIVE = 5  # Number of frames without movement to consider "arrived"

def init_drones():
    """Initialize friendly and enemy drones."""
    # Initialize friendly drones in a grid pattern
    num_friendly = 12
    cols = 4
    spacing = 80
    start_x = 200
    start_y = 200
    
    for i in range(num_friendly):
        row = i // cols
        col = i % cols
        drone_id = f"drone_{i+1}"
        world["drones"][drone_id] = Drone(
            id=drone_id,
            x=start_x + col * spacing,
            y=start_y + row * spacing,
            vx=0.0,
            vy=0.0,
            mode="idle",
            team="friendly",
            last_x=start_x + col * spacing,
            last_y=start_y + row * spacing,
            stuck_frames=0
        )
    
    # Initialize enemy drones with different patterns
    enemy_patterns = [
        {"pattern": "up_down", "x": 700, "y": 200, "range": 200},
        {"pattern": "up_down", "x": 800, "y": 300, "range": 150},
        {"pattern": "left_right", "x": 600, "y": 500, "range": 180},
        {"pattern": "left_right", "x": 750, "y": 600, "range": 160},
        {"pattern": "circular", "x": 500, "y": 400, "radius": 100},
        {"pattern": "circular", "x": 900, "y": 200, "radius": 80},
    ]
    
    for i, pattern_info in enumerate(enemy_patterns):
        enemy_id = f"enemy_{i+1}"
        pattern_data = {}
        
        if pattern_info["pattern"] == "up_down":
            pattern_data = {
                "center_y": pattern_info["y"],
                "range": pattern_info["range"],
                "direction": 1  # 1 for down, -1 for up
            }
        elif pattern_info["pattern"] == "left_right":
            pattern_data = {
                "center_x": pattern_info["x"],
                "range": pattern_info["range"],
                "direction": 1  # 1 for right, -1 for left
            }
        elif pattern_info["pattern"] == "circular":
            pattern_data = {
                "center_x": pattern_info["x"],
                "center_y": pattern_info["y"],
                "radius": pattern_info["radius"],
                "angle": 0.0  # Current angle in radians
            }
        
        world["drones"][enemy_id] = Drone(
            id=enemy_id,
            x=pattern_info["x"],
            y=pattern_info["y"],
            vx=0.0,
            vy=0.0,
            mode="pattern",
            team="enemy",
            pattern=pattern_info["pattern"],
            pattern_data=pattern_data
        )

def update_enemy_pattern(drone: Drone, dt: float) -> Drone:
    """Update enemy drone position based on movement pattern."""
    if drone.pattern_data is None:
        return drone
    
    if drone.pattern == "up_down":
        center_y = drone.pattern_data["center_y"]
        range_val = drone.pattern_data["range"]
        direction = drone.pattern_data["direction"]
        
        # Move up or down
        drone.y += direction * ENEMY_SPEED * dt
        
        # Check bounds and reverse direction
        if drone.y >= center_y + range_val:
            drone.y = center_y + range_val
            drone.pattern_data["direction"] = -1
        elif drone.y <= center_y - range_val:
            drone.y = center_y - range_val
            drone.pattern_data["direction"] = 1
        
        drone.vy = direction * ENEMY_SPEED
        drone.vx = 0.0
        
    elif drone.pattern == "left_right":
        center_x = drone.pattern_data["center_x"]
        range_val = drone.pattern_data["range"]
        direction = drone.pattern_data["direction"]
        
        # Move left or right
        drone.x += direction * ENEMY_SPEED * dt
        
        # Check bounds and reverse direction
        if drone.x >= center_x + range_val:
            drone.x = center_x + range_val
            drone.pattern_data["direction"] = -1
        elif drone.x <= center_x - range_val:
            drone.x = center_x - range_val
            drone.pattern_data["direction"] = 1
        
        drone.vx = direction * ENEMY_SPEED
        drone.vy = 0.0
        
    elif drone.pattern == "circular":
        center_x = drone.pattern_data["center_x"]
        center_y = drone.pattern_data["center_y"]
        radius = drone.pattern_data["radius"]
        angle = drone.pattern_data["angle"]
        
        # Update angle
        angular_speed = ENEMY_SPEED / radius
        angle += angular_speed * dt
        drone.pattern_data["angle"] = angle
        
        # Calculate position on circle
        drone.x = center_x + radius * math.cos(angle)
        drone.y = center_y + radius * math.sin(angle)
        
        # Calculate velocity (tangent to circle)
        drone.vx = -ENEMY_SPEED * math.sin(angle)
        drone.vy = ENEMY_SPEED * math.cos(angle)
    
    # Clamp to world bounds
    drone.x = max(0, min(WORLD_WIDTH, drone.x))
    drone.y = max(0, min(WORLD_HEIGHT, drone.y))
    
    return drone

def would_collide(drone: Drone, new_x: float, new_y: float, other_drones: List[Drone]) -> bool:
    """Check if moving to new position would cause a collision with another friendly drone."""
    for other in other_drones:
        if other.id == drone.id or other.team != "friendly":
            continue
        
        # Check distance to other drone's current position
        dx = new_x - other.x
        dy = new_y - other.y
        distance = math.sqrt(dx * dx + dy * dy)
        
        if distance < DRONE_HITBOX_RADIUS * 2:
            return True
    
    return False

def calculate_safe_movement(drone: Drone, desired_vx: float, desired_vy: float, dt: float, all_drones: List[Drone]) -> tuple:
    """Calculate safe movement that won't cause collisions. Returns (vx, vy, moved)."""
    new_x = drone.x + desired_vx * dt
    new_y = drone.y + desired_vy * dt
    
    # Check if this movement would cause a collision
    if would_collide(drone, new_x, new_y, all_drones):
        # Try reducing movement by 50%
        reduced_vx = desired_vx * 0.5
        reduced_vy = desired_vy * 0.5
        new_x = drone.x + reduced_vx * dt
        new_y = drone.y + reduced_vy * dt
        
        if would_collide(drone, new_x, new_y, all_drones):
            # Still would collide, try even smaller movement
            reduced_vx = desired_vx * 0.25
            reduced_vy = desired_vy * 0.25
            new_x = drone.x + reduced_vx * dt
            new_y = drone.y + reduced_vy * dt
            
            if would_collide(drone, new_x, new_y, all_drones):
                # Would still collide, don't move at all
                return (0.0, 0.0, False)
            else:
                return (reduced_vx, reduced_vy, True)
        else:
            return (reduced_vx, reduced_vy, True)
    else:
        return (desired_vx, desired_vy, True)

def update_drone(drone: Drone, dt: float, all_drones: List[Drone]) -> Drone:
    """Update drone position based on current velocity and target."""
    # Handle enemy pattern movement
    if drone.team == "enemy" and drone.mode == "pattern":
        return update_enemy_pattern(drone, dt)
    
    # Handle friendly drone movement with predictive collision avoidance
    if drone.team == "friendly":
        # Initialize position tracking
        if drone.last_x is None:
            drone.last_x = drone.x
            drone.last_y = drone.y
        
        old_x = drone.x
        old_y = drone.y
        
        if drone.mode == "moving" and drone.target_x is not None and drone.target_y is not None:
            # Calculate distance to target
            dx = drone.target_x - drone.x
            dy = drone.target_y - drone.y
            distance = math.sqrt(dx * dx + dy * dy)
            
            # Check if drone has been stuck (not moving) for several frames
            movement = math.sqrt((drone.x - drone.last_x) ** 2 + (drone.y - drone.last_y) ** 2)
            if movement < STUCK_THRESHOLD:
                drone.stuck_frames += 1
            else:
                drone.stuck_frames = 0
            
            # Consider arrived if stuck for enough frames (blocked by other drones)
            if drone.stuck_frames >= STUCK_FRAMES_TO_ARRIVE:
                # Drone is blocked, consider it arrived
                drone.vx = 0.0
                drone.vy = 0.0
                drone.mode = "idle"
                drone.target_x = None
                drone.target_y = None
                drone.stuck_frames = 0
            elif distance < 5.0:  # Close enough to target
                # Arrived at target
                drone.x = drone.target_x
                drone.y = drone.target_y
                drone.vx = 0.0
                drone.vy = 0.0
                drone.mode = "idle"
                drone.target_x = None
                drone.target_y = None
                drone.stuck_frames = 0
            else:
                # Calculate desired direction to target
                if distance > 0:
                    direction_x = dx / distance
                    direction_y = dy / distance
                else:
                    direction_x = 0
                    direction_y = 0
                
                # Desired velocity toward target
                target_vx = direction_x * DRONE_SPEED
                target_vy = direction_y * DRONE_SPEED
                
                # Calculate safe movement that won't cause collisions
                safe_vx, safe_vy, moved = calculate_safe_movement(drone, target_vx, target_vy, dt, all_drones)
                
                drone.vx = safe_vx
                drone.vy = safe_vy
                
                if moved:
                    # Update position
                    drone.x += drone.vx * dt
                    drone.y += drone.vy * dt
                    
                    # Clamp to world bounds
                    drone.x = max(0, min(WORLD_WIDTH, drone.x))
                    drone.y = max(0, min(WORLD_HEIGHT, drone.y))
                else:
                    # Can't move due to collision risk
                    drone.vx = 0.0
                    drone.vy = 0.0
        else:
            # Idle - no movement
            drone.vx = 0.0
            drone.vy = 0.0
            drone.stuck_frames = 0
        
        # Update position tracking
        drone.last_x = old_x
        drone.last_y = old_y
    
    return drone

def check_collisions():
    """Check for collisions between friendly and enemy drones and remove them."""
    drones_to_remove = set()
    
    friendly_drones = [d for d in world["drones"].values() if d.team == "friendly"]
    enemy_drones = [d for d in world["drones"].values() if d.team == "enemy"]
    
    for friendly in friendly_drones:
        if friendly.id in drones_to_remove:
            continue
        for enemy in enemy_drones:
            if enemy.id in drones_to_remove:
                continue
            
            dx = friendly.x - enemy.x
            dy = friendly.y - enemy.y
            distance = math.sqrt(dx * dx + dy * dy)
            
            # Collision when circle edges touch: distance between centers < sum of radii
            if distance < DRONE_RADIUS * 2:
                # Collision detected - remove both
                drones_to_remove.add(friendly.id)
                drones_to_remove.add(enemy.id)
                break
    
    # Remove collided drones
    for drone_id in drones_to_remove:
        if drone_id in world["drones"]:
            del world["drones"][drone_id]
    
    return len(drones_to_remove) > 0

async def simulation_loop():
    """Background task that updates drone positions."""
    while True:
        current_time = datetime.now().timestamp()
        dt = min(SIMULATION_DT, current_time - world["last_update"])
        world["last_update"] = current_time
        
        # Get all drones as a list for collision/separation calculations
        all_drones = list(world["drones"].values())
        
        # Update all drones
        for drone_id, drone in list(world["drones"].items()):
            world["drones"][drone_id] = update_drone(drone, dt, all_drones)
        
        # Check for collisions
        check_collisions()
        
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
            # Only allow moving friendly drones
            if drone.team == "friendly":
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

