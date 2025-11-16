"""
FastAPI backend for drone swarm simulation.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
from datetime import datetime
import math
import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
    mode: str = "idle"  # idle, moving, dispersing, pattern, patrol, tail, intercept
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    team: str = "friendly"  # friendly or enemy
    pattern: Optional[str] = None  # up_down, left_right, circular, None
    pattern_data: Optional[dict] = None  # Pattern-specific state
    patrol_start_x: Optional[float] = None  # Starting position for patrol
    patrol_start_y: Optional[float] = None
    patrol_target_x: Optional[float] = None  # Target position for patrol
    patrol_target_y: Optional[float] = None
    patrol_to_target: bool = True  # True = going to target, False = returning to start
    tail_target_id: Optional[str] = None  # ID of drone being tailed
    tail_distance: float = 80.0  # Desired distance to maintain from target
    intercept_target_id: Optional[str] = None  # ID of enemy drone being intercepted
    intercept_start_x: Optional[float] = None  # Starting X position when intercept began
    intercept_start_y: Optional[float] = None  # Starting Y position when intercept began
    base_id: str = "base_1"  # Which base this drone belongs to
    base_x: float = 0.0  # Home base X coordinate
    base_y: float = 0.0  # Home base Y coordinate
    base_shape: str = "circle"  # circle, square, triangle - visual shape of base
    last_x: Optional[float] = None  # Previous position for stuck detection
    last_y: Optional[float] = None
    stuck_frames: int = 0  # Number of frames without movement
    command_id: Optional[int] = None  # ID of the command group this drone belongs to

class WorldState(BaseModel):
    drones: List[Drone]
    timestamp: float

class Command(BaseModel):
    drone_ids: List[str]
    target_x: float
    target_y: float

class TaskExecution(BaseModel):
    task_name: str
    drone_ids: List[str]
    parameters: Dict[str, Any]

class NaturalLanguageCommand(BaseModel):
    command: str

class TaskResult(BaseModel):
    success: bool
    message: str
    task_name: str
    parameters: Dict[str, Any]

class SetBaseRequest(BaseModel):
    drone_ids: List[str]
    base_id: str

class PauseCommand(BaseModel):
    paused: bool

class TimeControlCommand(BaseModel):
    action: str  # "reverse", "forward", "jump_back"

# Base definitions
BASES = {
    "base_1": {"x": 100, "y": 900, "shape": "circle", "name": "Circle Base"},
    "base_2": {"x": 500, "y": 900, "shape": "square", "name": "Square Base"},
    "base_3": {"x": 900, "y": 900, "shape": "triangle", "name": "Triangle Base"}
}

# In-memory world state
world = {
    "drones": {},
    "last_update": datetime.now().timestamp(),
    "next_command_id": 1,  # Counter for command groups
    "task_results": [],  # Store task execution results for UI display
    "paused": False,
    "time_direction": 1,  # 1 for forward, -1 for reverse
    "history": [],  # List of world snapshots for time travel
    "history_index": -1  # Current position in history (-1 = live)
}

# Available tasks with their function definitions
AVAILABLE_TASKS = {
    "tail": {
        "description": "Follow an enemy drone while maintaining a certain distance",
        "parameters": {
            "enemy_drone": "string (enemy drone ID)",
            "friendly_drones": "list of string (friendly drone IDs)",
            "distance": "float (distance to maintain)"
        }
    },
    "patrol": {
        "description": "Patrol between two or more locations",
        "parameters": {
            "locations": "list of dict with x, y coordinates (at least 2 locations)",
            "friendly_drones": "list of string (friendly drone IDs)"
        }
    },
    "hold": {
        "description": "Stop selected drones at their current positions",
        "parameters": {
            "friendly_drones": "list of string (friendly drone IDs)"
        }
    },
    "return_to_base": {
        "description": "Send selected drones back to their home bases",
        "parameters": {
            "friendly_drones": "list of string (friendly drone IDs)"
        }
    },
    "intercept": {
        "description": "Intercept an enemy drone by calculating the best intercept route based on the enemy's movement pattern",
        "parameters": {
            "enemy_drone": "string (enemy drone ID)",
            "friendly_drones": "list of string (friendly drone IDs)"
        }
    }
}

# OpenAI client (will be initialized with API key)
openai_client = None

# Simulation parameters
DRONE_SPEED = 200.0  # pixels per second (increased for faster movement)
ENEMY_SPEED = 40.0  # pixels per second for enemy drones
WORLD_WIDTH = 1000
WORLD_HEIGHT = 1000
GRID_COLS = 10  # A-J (10 columns)
GRID_ROWS = 10  # 1-10 (10 rows)
CELL_SIZE = WORLD_WIDTH / GRID_COLS  # 100 pixels per cell
SIMULATION_DT = 0.02  # 20ms update interval (50Hz for smooth physics)
DRONE_VISUAL_RADIUS = 13.0  # Visual radius of drones (increased for better visibility)
DRONE_STROKE_WIDTH = 3.0  # Maximum stroke width (selected drones have strokeWidth=3, unselected=2)
# In SVG, stroke is centered on the path, so outer edge is at radius + strokeWidth/2
# But we'll use radius + strokeWidth to ensure we catch all collisions including the full stroke
DRONE_HITBOX_RADIUS = DRONE_VISUAL_RADIUS + (DRONE_STROKE_WIDTH / 2.0)  # Total hitbox includes outer stroke edge
DRONE_RADIUS = DRONE_HITBOX_RADIUS  # Use hitbox radius for collision detection
GRID_SPACING = DRONE_VISUAL_RADIUS * 2.0  # Spacing between drones in grid (minimal buffer)
STUCK_THRESHOLD = 0.5  # Movement threshold to consider drone as having moved (pixels)
STUCK_FRAMES_TO_ARRIVE = 5  # Number of frames without movement to consider "arrived"
HISTORY_MAX_LENGTH = 500  # Store 500 snapshots (10 seconds at 50Hz)
HISTORY_SAVE_INTERVAL = 1  # Save every frame

def init_drones():
    """Initialize friendly and enemy drones."""
    # Initialize friendly drones in a square formation at their home bases
    num_friendly = 12
    drones_per_base = 4
    formation_spacing = 50  # Spacing between drones in square formation
    
    for i in range(num_friendly):
        drone_id = f"drone_{i+1}"
        
        # Assign bases: first 4 to base_1, next 4 to base_2, last 4 to base_3
        if i < 4:
            base_id = "base_1"
            formation_index = i
        elif i < 8:
            base_id = "base_2"
            formation_index = i - 4
        else:
            base_id = "base_3"
            formation_index = i - 8
        
        base = BASES[base_id]
        
        # Calculate position in 2x2 square formation around the base
        # Formation: 2 columns, 2 rows
        col = formation_index % 2  # 0 or 1
        row = formation_index // 2  # 0 or 1
        
        # Center the formation on the base
        offset_x = (col - 0.5) * formation_spacing
        offset_y = (row - 0.5) * formation_spacing
        
        drone_x = base["x"] + offset_x
        drone_y = base["y"] + offset_y
        
        world["drones"][drone_id] = Drone(
            id=drone_id,
            x=drone_x,
            y=drone_y,
            vx=0.0,
            vy=0.0,
            mode="idle",
            team="friendly",
            base_id=base_id,
            base_x=base["x"],
            base_y=base["y"],
            base_shape=base["shape"]
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

def predict_enemy_position(enemy_drone: Drone, t: float) -> tuple:
    """Predict enemy drone position at time t based on its movement pattern."""
    if enemy_drone.pattern_data is None:
        return (enemy_drone.x, enemy_drone.y)
    
    if enemy_drone.pattern == "up_down":
        center_y = enemy_drone.pattern_data["center_y"]
        range_val = enemy_drone.pattern_data["range"]
        direction = enemy_drone.pattern_data["direction"]
        current_y = enemy_drone.y
        
        # Calculate distance traveled in time t
        distance = direction * ENEMY_SPEED * t
        new_y = current_y + distance
        
        # Handle bouncing at boundaries
        while new_y > center_y + range_val or new_y < center_y - range_val:
            if new_y > center_y + range_val:
                # Hit top boundary, reverse
                excess = new_y - (center_y + range_val)
                new_y = center_y + range_val - excess
                direction = -1
            elif new_y < center_y - range_val:
                # Hit bottom boundary, reverse
                excess = (center_y - range_val) - new_y
                new_y = center_y - range_val + excess
                direction = 1
        
        return (enemy_drone.x, new_y)
    
    elif enemy_drone.pattern == "left_right":
        center_x = enemy_drone.pattern_data["center_x"]
        range_val = enemy_drone.pattern_data["range"]
        direction = enemy_drone.pattern_data["direction"]
        current_x = enemy_drone.x
        
        # Calculate distance traveled in time t
        distance = direction * ENEMY_SPEED * t
        new_x = current_x + distance
        
        # Handle bouncing at boundaries
        while new_x > center_x + range_val or new_x < center_x - range_val:
            if new_x > center_x + range_val:
                # Hit right boundary, reverse
                excess = new_x - (center_x + range_val)
                new_x = center_x + range_val - excess
                direction = -1
            elif new_x < center_x - range_val:
                # Hit left boundary, reverse
                excess = (center_x - range_val) - new_x
                new_x = center_x - range_val + excess
                direction = 1
        
        return (new_x, enemy_drone.y)
    
    elif enemy_drone.pattern == "circular":
        center_x = enemy_drone.pattern_data["center_x"]
        center_y = enemy_drone.pattern_data["center_y"]
        radius = enemy_drone.pattern_data["radius"]
        angle = enemy_drone.pattern_data["angle"]
        
        # Calculate new angle
        angular_speed = ENEMY_SPEED / radius
        new_angle = angle + angular_speed * t
        
        # Calculate position on circle
        new_x = center_x + radius * math.cos(new_angle)
        new_y = center_y + radius * math.sin(new_angle)
        
        return (new_x, new_y)
    
    # Fallback to current position
    return (enemy_drone.x, enemy_drone.y)

def calculate_intercept_point(friendly_x: float, friendly_y: float, enemy_drone: Drone) -> tuple:
    """Calculate the best intercept point for a friendly drone to reach an enemy drone.
    Returns (intercept_x, intercept_y, intercept_time)"""
    best_time = None
    best_intercept = None
    min_intercept_time = float('inf')
    
    # Search for intercept time between 0 and 30 seconds, in 0.1s steps
    for t in range(0, 300):  # 0 to 30 seconds in 0.1s increments
        t_sec = t / 10.0
        enemy_x, enemy_y = predict_enemy_position(enemy_drone, t_sec)
        
        # Calculate distance to that point
        dx = enemy_x - friendly_x
        dy = enemy_y - friendly_y
        distance = math.sqrt(dx * dx + dy * dy)
        
        # Calculate time needed for friendly drone to reach that point
        time_needed = distance / DRONE_SPEED
        
        # Check if we can reach it in time (with small margin for approximation)
        if time_needed <= t_sec + 0.1:  # Can reach it
            if t_sec < min_intercept_time:
                min_intercept_time = t_sec
                best_time = t_sec
                best_intercept = (enemy_x, enemy_y)
    
    # If we found a good intercept, use it
    if best_intercept:
        return (best_intercept[0], best_intercept[1], best_time)
    
    # Fallback: just head towards current enemy position
    return (enemy_drone.x, enemy_drone.y, math.sqrt((enemy_drone.x - friendly_x)**2 + (enemy_drone.y - friendly_y)**2) / DRONE_SPEED)

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

def calculate_grid_positions(num_drones: int, center_x: float, center_y: float) -> List[tuple]:
    """Calculate grid positions for drones in a square pattern centered around a point."""
    if num_drones == 0:
        return []
    
    # Calculate grid dimensions (square as much as possible)
    cols = int(math.ceil(math.sqrt(num_drones)))
    rows = int(math.ceil(num_drones / cols))
    
    positions = []
    spacing = GRID_SPACING
    
    # Calculate starting position (top-left of grid)
    total_width = (cols - 1) * spacing
    total_height = (rows - 1) * spacing
    start_x = center_x - total_width / 2.0
    start_y = center_y - total_height / 2.0
    
    # Generate positions in row-major order
    for i in range(num_drones):
        row = i // cols
        col = i % cols
        x = start_x + col * spacing
        y = start_y + row * spacing
        positions.append((x, y))
    
    return positions

def all_group_drones_arrived(command_id: int, all_drones: List[Drone]) -> bool:
    """Check if all drones in a command group have arrived at the destination."""
    group_drones = [d for d in all_drones if d.command_id == command_id and d.mode == "moving"]
    
    if len(group_drones) == 0:
        return True  # No moving drones in group
    
    # Check if all drones are close to their target
    for drone in group_drones:
        if drone.target_x is None or drone.target_y is None:
            continue
        dx = drone.target_x - drone.x
        dy = drone.target_y - drone.y
        distance = math.sqrt(dx * dx + dy * dy)
        if distance > 5.0:  # Not close enough yet
            return False
    
    return True

def disperse_group(command_id: int, all_drones: List[Drone], target_x: float, target_y: float):
    """Disperse a group of drones into a square grid around the target."""
    group_drones = [d for d in all_drones if d.command_id == command_id and d.team == "friendly"]
    
    if len(group_drones) == 0:
        return
    
    # Calculate grid positions
    grid_positions = calculate_grid_positions(len(group_drones), target_x, target_y)
    
    # Assign grid positions to drones
    for i, drone in enumerate(group_drones):
        if i < len(grid_positions):
            drone.target_x = grid_positions[i][0]
            drone.target_y = grid_positions[i][1]
            drone.mode = "dispersing"

def update_drone(drone: Drone, dt: float, all_drones: List[Drone]) -> Drone:
    """Update drone position based on current velocity and target."""
    # Handle enemy pattern movement
    if drone.team == "enemy" and drone.mode == "pattern":
        return update_enemy_pattern(drone, dt)
    
    # Handle friendly drone movement
    if drone.team == "friendly":
        # Handle tail mode: follow target drone while maintaining distance
        if drone.mode == "tail" and drone.tail_target_id is not None:
            # Find the target drone
            target_drone = None
            for d in all_drones:
                if d.id == drone.tail_target_id:
                    target_drone = d
                    break
            
            if target_drone and target_drone.id != drone.id:
                # Calculate distance to target
                dx = target_drone.x - drone.x
                dy = target_drone.y - drone.y
                distance = math.sqrt(dx * dx + dy * dy)
                
                # Calculate desired position (maintain tail_distance from target)
                if distance > 0:
                    direction_x = dx / distance
                    direction_y = dy / distance
                else:
                    direction_x = 0
                    direction_y = 0
                
                # If too far, move closer. If too close, move away
                distance_error = distance - drone.tail_distance
                
                if abs(distance_error) > 2.0:  # Only move if outside acceptable range (reduced for smoother movement)
                    if distance_error > 0:
                        # Too far - move towards target
                        drone.vx = direction_x * DRONE_SPEED
                        drone.vy = direction_y * DRONE_SPEED
                    else:
                        # Too close - move away from target
                        drone.vx = -direction_x * DRONE_SPEED
                        drone.vy = -direction_y * DRONE_SPEED
                    
                    # Update position
                    drone.x += drone.vx * dt
                    drone.y += drone.vy * dt
                    
                    # Clamp to world bounds
                    drone.x = max(0, min(WORLD_WIDTH, drone.x))
                    drone.y = max(0, min(WORLD_HEIGHT, drone.y))
                else:
                    # Within acceptable range - hold position
                    drone.vx = 0.0
                    drone.vy = 0.0
            else:
                # Target not found or invalid - go idle
                drone.mode = "idle"
                drone.tail_target_id = None
                drone.vx = 0.0
                drone.vy = 0.0
        
        # Handle intercept mode: intercept enemy drone, then return to start if another drone succeeded
        elif drone.mode == "intercept" and drone.intercept_target_id is not None:
            # Find the target enemy drone
            enemy_target = None
            for d in all_drones:
                if d.id == drone.intercept_target_id:
                    enemy_target = d
                    break
            
            if not enemy_target:
                # Enemy not found - return to start
                if drone.intercept_start_x is not None and drone.intercept_start_y is not None:
                    drone.target_x = drone.intercept_start_x
                    drone.target_y = drone.intercept_start_y
                    drone.mode = "moving"
                    drone.intercept_target_id = None
                else:
                    drone.mode = "idle"
                    drone.intercept_target_id = None
            else:
                # Check if any friendly drone has already intercepted this enemy
                # Check distance to enemy for all drones intercepting the same target
                dx_to_enemy = enemy_target.x - drone.x
                dy_to_enemy = enemy_target.y - drone.y
                distance_to_enemy = math.sqrt(dx_to_enemy * dx_to_enemy + dy_to_enemy * dy_to_enemy)
                
                # Check if this drone has intercepted
                if distance_to_enemy < DRONE_RADIUS * 2:
                    # This drone intercepted! Return to start
                    if drone.intercept_start_x is not None and drone.intercept_start_y is not None:
                        drone.target_x = drone.intercept_start_x
                        drone.target_y = drone.intercept_start_y
                        drone.mode = "moving"
                        drone.intercept_target_id = None
                        drone.intercept_start_x = None
                        drone.intercept_start_y = None
                else:
                    # Check if any other drone has intercepted this enemy
                    enemy_intercepted = False
                    for d in all_drones:
                        if (d.team == "friendly" and 
                            d.intercept_target_id == drone.intercept_target_id and
                            d.id != drone.id):
                            # Check if this other drone has reached the enemy
                            dx_other = enemy_target.x - d.x
                            dy_other = enemy_target.y - d.y
                            distance_other = math.sqrt(dx_other * dx_other + dy_other * dy_other)
                            if distance_other < DRONE_RADIUS * 2:  # Collision distance
                                enemy_intercepted = True
                                break
                    
                    if enemy_intercepted:
                        # Another drone intercepted - return to start
                        if drone.intercept_start_x is not None and drone.intercept_start_y is not None:
                            drone.target_x = drone.intercept_start_x
                            drone.target_y = drone.intercept_start_y
                            drone.mode = "moving"
                            drone.intercept_target_id = None
                            drone.intercept_start_x = None
                            drone.intercept_start_y = None
                    else:
                        # Still intercepting - recalculate intercept point periodically
                        intercept_x, intercept_y, _ = calculate_intercept_point(
                            drone.x, drone.y, enemy_target
                        )
                        
                        # Update target if significantly different (to avoid constant recalculations)
                        if drone.target_x is None or drone.target_y is None:
                            drone.target_x = intercept_x
                            drone.target_y = intercept_y
                        else:
                            dx_target = abs(drone.target_x - intercept_x)
                            dy_target = abs(drone.target_y - intercept_y)
                            if dx_target > 10 or dy_target > 10:  # Update if target changed significantly
                                drone.target_x = intercept_x
                                drone.target_y = intercept_y
                        
                        # Move toward intercept point (same as moving mode)
                        if drone.target_x is not None and drone.target_y is not None:
                            dx = drone.target_x - drone.x
                            dy = drone.target_y - drone.y
                            distance = math.sqrt(dx * dx + dy * dy)
                            
                            if distance < 5.0:  # Close enough to intercept point
                                # Reached intercept point, but enemy might have moved - recalculate
                                intercept_x, intercept_y, _ = calculate_intercept_point(
                                    drone.x, drone.y, enemy_target
                                )
                                drone.target_x = intercept_x
                                drone.target_y = intercept_y
                            else:
                                # Move toward intercept point
                                if distance > 0:
                                    direction_x = dx / distance
                                    direction_y = dy / distance
                                else:
                                    direction_x = 0
                                    direction_y = 0
                                
                                drone.vx = direction_x * DRONE_SPEED
                                drone.vy = direction_y * DRONE_SPEED
                                
                                # Update position
                                drone.x += drone.vx * dt
                                drone.y += drone.vy * dt
                                
                                # Clamp to world bounds
                                drone.x = max(0, min(WORLD_WIDTH, drone.x))
                                drone.y = max(0, min(WORLD_HEIGHT, drone.y))
        
        # Handle patrol mode: go back and forth between start and target positions
        elif drone.mode == "patrol" and drone.patrol_start_x is not None and drone.patrol_target_x is not None:
            # Determine current target (start or patrol target)
            if drone.patrol_to_target:
                target_x = drone.patrol_target_x
                target_y = drone.patrol_target_y
            else:
                target_x = drone.patrol_start_x
                target_y = drone.patrol_start_y
            
            # Calculate distance to current target
            dx = target_x - drone.x
            dy = target_y - drone.y
            distance = math.sqrt(dx * dx + dy * dy)
            
            # Check if arrived at current patrol point
            if distance < 5.0:
                # Arrived - switch direction
                drone.patrol_to_target = not drone.patrol_to_target
                drone.x = target_x
                drone.y = target_y
                drone.vx = 0.0
                drone.vy = 0.0
            else:
                # Move towards current patrol point
                if distance > 0:
                    direction_x = dx / distance
                    direction_y = dy / distance
                else:
                    direction_x = 0
                    direction_y = 0
                
                drone.vx = direction_x * DRONE_SPEED
                drone.vy = direction_y * DRONE_SPEED
                
                # Update position
                drone.x += drone.vx * dt
                drone.y += drone.vy * dt
                
                # Clamp to world bounds
                drone.x = max(0, min(WORLD_WIDTH, drone.x))
                drone.y = max(0, min(WORLD_HEIGHT, drone.y))
        
        elif drone.mode == "moving" and drone.target_x is not None and drone.target_y is not None:
            # Simple movement toward target (can overlap)
            dx = drone.target_x - drone.x
            dy = drone.target_y - drone.y
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance < 5.0:  # Close enough to target
                # Arrived at target - snap to it
                drone.x = drone.target_x
                drone.y = drone.target_y
                drone.vx = 0.0
                drone.vy = 0.0
                
                # Check if all drones in group have arrived
                if drone.command_id is not None:
                    if all_group_drones_arrived(drone.command_id, all_drones):
                        # All arrived - trigger dispersion
                        disperse_group(drone.command_id, all_drones, drone.target_x, drone.target_y)
                        # This drone will be set to dispersing mode by disperse_group
                        return drone
                
                # Not all arrived yet, stay in moving mode
            else:
                # Move toward target
                if distance > 0:
                    direction_x = dx / distance
                    direction_y = dy / distance
                else:
                    direction_x = 0
                    direction_y = 0
                
                drone.vx = direction_x * DRONE_SPEED
                drone.vy = direction_y * DRONE_SPEED
                
                # Update position
                drone.x += drone.vx * dt
                drone.y += drone.vy * dt
                
                # Clamp to world bounds
                drone.x = max(0, min(WORLD_WIDTH, drone.x))
                drone.y = max(0, min(WORLD_HEIGHT, drone.y))
        
        elif drone.mode == "dispersing" and drone.target_x is not None and drone.target_y is not None:
            # Moving to grid position
            dx = drone.target_x - drone.x
            dy = drone.target_y - drone.y
            distance = math.sqrt(dx * dx + dy * dy)
            
            if distance < 2.0:  # Arrived at grid position
                drone.x = drone.target_x
                drone.y = drone.target_y
                drone.vx = 0.0
                drone.vy = 0.0
                drone.mode = "idle"
                drone.target_x = None
                drone.target_y = None
                drone.command_id = None
            else:
                # Move toward grid position with deceleration to prevent overshooting
                if distance > 0:
                    direction_x = dx / distance
                    direction_y = dy / distance
                else:
                    direction_x = 0
                    direction_y = 0
                
                # Decelerate as we approach target to prevent overshooting
                # At high speeds, we need to slow down when close to target
                deceleration_distance = max(10.0, DRONE_SPEED * dt * 2)  # Slow down when within 2 frames of travel
                if distance < deceleration_distance:
                    # Scale speed based on distance (smooth deceleration)
                    speed_factor = distance / deceleration_distance
                    current_speed = DRONE_SPEED * speed_factor
                else:
                    current_speed = DRONE_SPEED
                
                drone.vx = direction_x * current_speed
                drone.vy = direction_y * current_speed
                
                # Update position
                drone.x += drone.vx * dt
                drone.y += drone.vy * dt
                
                # Clamp to world bounds
                drone.x = max(0, min(WORLD_WIDTH, drone.x))
                drone.y = max(0, min(WORLD_HEIGHT, drone.y))
        
        else:
            # Idle - no movement
            drone.vx = 0.0
            drone.vy = 0.0
    
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

def save_history_snapshot():
    """Save current world state to history."""
    # Create a deep copy of current state
    snapshot = {
        "drones": {drone_id: drone.model_copy(deep=True) for drone_id, drone in world["drones"].items()},
        "timestamp": world["last_update"]
    }
    
    # Add snapshot to history
    world["history"].append(snapshot)
    
    # Limit history size (keep only recent history)
    if len(world["history"]) > HISTORY_MAX_LENGTH:
        world["history"].pop(0)
    
    # Always point to the end when recording new history
    world["history_index"] = len(world["history"]) - 1

def restore_from_history(index: int):
    """Restore world state from history at given index."""
    if 0 <= index < len(world["history"]):
        snapshot = world["history"][index]
        world["drones"] = {drone_id: drone.model_copy(deep=True) for drone_id, drone in snapshot["drones"].items()}
        world["last_update"] = snapshot["timestamp"]
        world["history_index"] = index
        return True
    return False

async def simulation_loop():
    """Background task that updates drone positions."""
    frame_count = 0
    while True:
        current_time = datetime.now().timestamp()
        dt = min(SIMULATION_DT, current_time - world["last_update"])
        world["last_update"] = current_time
        
        # Handle pause
        if world["paused"]:
            await asyncio.sleep(SIMULATION_DT)
            continue
        
        # Handle time reversal
        if world["time_direction"] == -1:
            # Go backwards in history
            if world["history_index"] > 0:
                restore_from_history(world["history_index"] - 1)
            await asyncio.sleep(SIMULATION_DT)
            continue
        
        # Normal forward simulation
        # Get all drones as a list for collision/separation calculations
        all_drones = list(world["drones"].values())
        
        # Update all drones
        for drone_id, drone in list(world["drones"].items()):
            world["drones"][drone_id] = update_drone(drone, dt, all_drones)
        
        # Check for collisions
        check_collisions()
        
        # Save history snapshot
        frame_count += 1
        if frame_count % HISTORY_SAVE_INTERVAL == 0:
            save_history_snapshot()
        
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

# Task functions that actually control drones
def tail_task(enemy_drone: str, friendly_drones: List[str] = None, distance: float = 50.0):
    """Tail task - sets drones to follow an enemy drone."""
    if friendly_drones is None:
        friendly_drones = []
    
    # Hardcode distance to 50
    distance = 50.0
    
    # Verify enemy drone exists
    if enemy_drone not in world["drones"]:
        result = {
            "task_name": "tail",
            "parameters": {
                "enemy_drone": enemy_drone,
                "friendly_drones": friendly_drones
            },
            "success": False,
            "message": f"Enemy drone {enemy_drone} not found"
        }
        world["task_results"].append(result)
        return result
    
    updated_count = 0
    for drone_id in friendly_drones:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly" and drone_id != enemy_drone:
                drone.mode = "tail"
                drone.tail_target_id = enemy_drone
                drone.tail_distance = distance  # Always 50
                drone.vx = 0.0
                drone.vy = 0.0
                drone.command_id = None  # Tail doesn't use command groups
                world["drones"][drone_id] = drone
                updated_count += 1
    
    result = {
        "task_name": "tail",
        "parameters": {
            "enemy_drone": enemy_drone,
            "friendly_drones": friendly_drones
        },
        "success": True,
        "updated_drones": updated_count
    }
    world["task_results"].append(result)
    return result

def patrol_task(locations: List[Dict[str, float]] = None, friendly_drones: List[str] = None):
    """Patrol task - sets drones to patrol between exactly 2 locations."""
    if locations is None or len(locations) != 2:
        result = {
            "task_name": "patrol",
            "parameters": {
                "locations": locations or [],
                "friendly_drones": friendly_drones or []
            },
            "success": False,
            "message": "Patrol requires exactly 2 locations"
        }
        world["task_results"].append(result)
        return result
    
    if friendly_drones is None:
        friendly_drones = []
    
    updated_count = 0
    # For now, patrol between first two locations (can be extended later)
    start_loc = locations[0]
    target_loc = locations[1]
    
    for drone_id in friendly_drones:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly":
                drone.mode = "patrol"
                drone.patrol_start_x = start_loc.get("x", drone.x)
                drone.patrol_start_y = start_loc.get("y", drone.y)
                drone.patrol_target_x = target_loc.get("x", drone.x)
                drone.patrol_target_y = target_loc.get("y", drone.y)
                # Start by going to the first location (start), then to the second (target)
                drone.patrol_to_target = False  # False = go to start first, True = go to target
                drone.vx = 0.0
                drone.vy = 0.0
                drone.command_id = None  # Patrol doesn't use command groups
                world["drones"][drone_id] = drone
                updated_count += 1
    
    result = {
        "task_name": "patrol",
        "parameters": {
            "locations": locations,
            "friendly_drones": friendly_drones
        },
        "success": True,
        "updated_drones": updated_count
    }
    world["task_results"].append(result)
    return result

def hold_task(friendly_drones: List[str] = None):
    """Hold task - stops selected drones."""
    if friendly_drones is None:
        friendly_drones = []
    
    updated_count = 0
    for drone_id in friendly_drones:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly":
                drone.mode = "idle"
                drone.vx = 0.0
                drone.vy = 0.0
                drone.target_x = None
                drone.target_y = None
                drone.command_id = None
                world["drones"][drone_id] = drone
                updated_count += 1
    
    result = {
        "task_name": "hold",
        "parameters": {
            "friendly_drones": friendly_drones
        },
        "success": True,
        "updated_drones": updated_count
    }
    world["task_results"].append(result)
    return result

def return_to_base_task(friendly_drones: List[str] = None):
    """Return to base task - sends drones back to their home bases."""
    if friendly_drones is None:
        friendly_drones = []
    
    updated_count = 0
    for drone_id in friendly_drones:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly":
                drone.mode = "moving"
                drone.target_x = drone.base_x
                drone.target_y = drone.base_y
                drone.vx = 0.0
                drone.vy = 0.0
                drone.command_id = None  # Return to base doesn't use command groups
                world["drones"][drone_id] = drone
                updated_count += 1
    
    result = {
        "task_name": "return_to_base",
        "parameters": {
            "friendly_drones": friendly_drones
        },
        "success": True,
        "updated_drones": updated_count
    }
    world["task_results"].append(result)
    return result

def intercept_task(enemy_drone: str, friendly_drones: List[str] = None):
    """Intercept task - sets drones to intercept an enemy drone using predicted movement."""
    if friendly_drones is None:
        friendly_drones = []
    
    # Verify enemy drone exists
    if enemy_drone not in world["drones"]:
        result = {
            "task_name": "intercept",
            "parameters": {
                "enemy_drone": enemy_drone,
                "friendly_drones": friendly_drones
            },
            "success": False,
            "message": f"Enemy drone {enemy_drone} not found"
        }
        world["task_results"].append(result)
        return result
    
    enemy = world["drones"][enemy_drone]
    if enemy.team != "enemy":
        result = {
            "task_name": "intercept",
            "parameters": {
                "enemy_drone": enemy_drone,
                "friendly_drones": friendly_drones
            },
            "success": False,
            "message": f"Drone {enemy_drone} is not an enemy drone"
        }
        world["task_results"].append(result)
        return result
    
    updated_count = 0
    for drone_id in friendly_drones:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly" and drone_id != enemy_drone:
                # Calculate intercept point
                intercept_x, intercept_y, intercept_time = calculate_intercept_point(
                    drone.x, drone.y, enemy
                )
                
                # Store starting position for return
                drone.intercept_start_x = drone.x
                drone.intercept_start_y = drone.y
                drone.intercept_target_id = enemy_drone
                drone.mode = "intercept"
                drone.target_x = intercept_x
                drone.target_y = intercept_y
                drone.vx = 0.0
                drone.vy = 0.0
                drone.command_id = None  # Intercept doesn't use command groups
                world["drones"][drone_id] = drone
                updated_count += 1
    
    result = {
        "task_name": "intercept",
        "parameters": {
            "enemy_drone": enemy_drone,
            "friendly_drones": friendly_drones
        },
        "success": True,
        "updated_drones": updated_count
    }
    world["task_results"].append(result)
    return result

# Task function registry
TASK_FUNCTIONS = {
    "tail": tail_task,
    "patrol": patrol_task,
    "hold": hold_task,
    "return_to_base": return_to_base_task,
    "intercept": intercept_task
}

@app.get("/tasks")
async def get_available_tasks():
    """Get list of available tasks."""
    return {"tasks": AVAILABLE_TASKS}

@app.get("/bases")
async def get_bases():
    """Get all available bases."""
    return {"bases": BASES}

@app.post("/set-base")
async def set_base(request: SetBaseRequest):
    """Set the home base for selected drones."""
    if request.base_id not in BASES:
        return {"success": False, "message": f"Base {request.base_id} not found"}
    
    base = BASES[request.base_id]
    updated_count = 0
    
    for drone_id in request.drone_ids:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            if drone.team == "friendly":
                drone.base_id = request.base_id
                drone.base_x = base["x"]
                drone.base_y = base["y"]
                drone.base_shape = base["shape"]
                world["drones"][drone_id] = drone
                updated_count += 1
    
    return {"success": True, "updated_drones": updated_count}

@app.post("/pause")
async def pause_simulation(command: PauseCommand):
    """Pause or unpause the simulation."""
    world["paused"] = command.paused
    return {"status": "ok", "paused": world["paused"]}

@app.post("/time-control")
async def time_control(command: TimeControlCommand):
    """Control time: reverse, forward, or jump back."""
    if command.action == "reverse":
        # Toggle reverse mode
        if world["time_direction"] == 1:
            world["time_direction"] = -1
            world["paused"] = False
        else:
            world["time_direction"] = 1
        return {"status": "ok", "time_direction": world["time_direction"]}
    
    elif command.action == "forward":
        # Set to forward mode
        world["time_direction"] = 1
        world["paused"] = False
        return {"status": "ok", "time_direction": world["time_direction"]}
    
    elif command.action == "jump_back":
        # Jump back 5 seconds (250 frames at 50Hz)
        frames_to_jump = 250
        
        # Calculate target index from current position in history
        if world["history_index"] < 0:
            # Not in history mode, use the latest
            target_index = max(0, len(world["history"]) - 1 - frames_to_jump)
        else:
            # Already in history, jump back from current position
            target_index = max(0, world["history_index"] - frames_to_jump)
        
        if len(world["history"]) > 0 and restore_from_history(target_index):
            # Resume normal forward simulation from this point
            world["time_direction"] = 1
            world["paused"] = False
            return {"status": "ok", "jumped_to_index": target_index, "history_length": len(world["history"])}
        else:
            return {"status": "error", "message": "Not enough history to jump back 5 seconds"}
    
    return {"status": "error", "message": "Invalid action"}

@app.post("/reset")
async def reset_simulation():
    """Reset the simulation by reinitializing drones and clearing history."""
    # Clear current drones and history
    world["drones"] = {}
    world["history"] = []
    world["history_index"] = -1
    world["next_command_id"] = 1
    world["paused"] = False
    world["time_direction"] = 1
    world["task_results"] = []
    
    # Reinitialize drones
    init_drones()
    
    return {"status": "ok", "message": "Simulation reset"}

@app.post("/task/execute")
async def execute_task(task_execution: TaskExecution):
    """Execute a task via UI."""
    if task_execution.task_name not in TASK_FUNCTIONS:
        return {"success": False, "message": f"Unknown task: {task_execution.task_name}"}
    
    task_func = TASK_FUNCTIONS[task_execution.task_name]
    
    # Call the task function with parameters
    try:
        result = task_func(**task_execution.parameters)
        return {
            "success": True,
            "message": f"Task {task_execution.task_name} executed",
            "task_name": result["task_name"],
            "parameters": result["parameters"]
        }
    except Exception as e:
        return {"success": False, "message": f"Error executing task: {str(e)}"}

@app.get("/task/results")
async def get_task_results():
    """Get recent task execution results."""
    results = world["task_results"][-10:]  # Last 10 results
    return {"results": results}

@app.post("/command")
async def send_command(command: Command):
    """Send a command to move selected drones to a target location."""
    # Assign the same command_id to all drones in this command
    command_id = world["next_command_id"]
    world["next_command_id"] += 1
    
    updated_count = 0
    for drone_id in command.drone_ids:
        if drone_id in world["drones"]:
            drone = world["drones"][drone_id]
            # Only allow moving friendly drones
            if drone.team == "friendly":
                drone.target_x = command.target_x
                drone.target_y = command.target_y
                drone.mode = "moving"
                drone.command_id = command_id  # Assign group ID
                drone.stuck_frames = 0  # Reset stuck counter for new command
                world["drones"][drone_id] = drone
                updated_count += 1
    
    return {
        "status": "ok",
        "updated_drones": updated_count,
        "target": {"x": command.target_x, "y": command.target_y}
    }

def chess_notation_to_coords(notation: str) -> tuple:
    """Convert chess notation (e.g., 'B4', 'A1', 'T20') to (x, y) coordinates.
    
    Args:
        notation: Chess-style notation like 'B4' (letter + number)
        
    Returns:
        Tuple of (x, y) coordinates in world space, or None if invalid
    """
    if not notation or len(notation) < 2:
        return None
    
    # Extract letter and number
    letter = notation[0].upper()
    try:
        number = int(notation[1:])
    except ValueError:
        return None
    
    # Convert letter to column index (A=0, B=1, ..., J=9)
    if letter < 'A' or letter > 'J':
        return None
    col_index = ord(letter) - ord('A')
    
    # Convert number to row index (1=0, 2=1, ..., 10=9)
    if number < 1 or number > GRID_ROWS:
        return None
    row_index = number - 1
    
    # Calculate center of cell
    x = col_index * CELL_SIZE + CELL_SIZE / 2
    y = row_index * CELL_SIZE + CELL_SIZE / 2
    
    return (x, y)

def get_world_context() -> str:
    """Get current world state as context for LLM, including distance calculations."""
    friendly_drones = [d for d in world["drones"].values() if d.team == "friendly"]
    enemy_drones = [d for d in world["drones"].values() if d.team == "enemy"]
    
    # Calculate distances from each friendly drone to each enemy drone
    # This helps the LLM identify "closest" drones accurately
    friendly_with_distances = []
    for friendly in friendly_drones:
        distances_to_enemies = {}
        for enemy in enemy_drones:
            dx = enemy.x - friendly.x
            dy = enemy.y - friendly.y
            distance = math.sqrt(dx * dx + dy * dy)
            distances_to_enemies[enemy.id] = round(distance, 1)
        friendly_with_distances.append({
            "id": friendly.id,
            "x": round(friendly.x, 1),
            "y": round(friendly.y, 1),
            "distances_to_enemies": distances_to_enemies
        })
    
    # Pre-calculate closest drones for each enemy in sorted order (closest first)
    closest_drones_by_enemy = {}
    for enemy in enemy_drones:
        # Find distances from all friendly drones to this enemy
        distances = []
        for friendly in friendly_drones:
            dx = enemy.x - friendly.x
            dy = enemy.y - friendly.y
            distance = math.sqrt(dx * dx + dy * dy)
            distances.append((friendly.id, round(distance, 1)))
        
        # Sort by distance (closest first)
        distances.sort(key=lambda x: x[1])
        
        # Extract just the drone IDs in sorted order (closest first)
        sorted_drone_ids = [drone_id for drone_id, _ in distances]
        
        # Store both the single closest and the full sorted list
        if distances:
            closest_drones_by_enemy[enemy.id] = {
                "closest_drone": distances[0][0],  # Single closest (for backward compatibility)
                "distance": distances[0][1],
                "closest_drones_sorted": sorted_drone_ids,  # All drones sorted by distance (closest first)
                "distances_sorted": distances  # Full list with distances for reference
            }
    
    context = {
        "friendly_drones": friendly_with_distances,
        "enemy_drones": [
            {"id": d.id, "x": round(d.x, 1), "y": round(d.y, 1)} for d in enemy_drones
        ],
        "closest_drones": closest_drones_by_enemy  # Pre-calculated: enemy_id -> closest friendly drone
    }
    return json.dumps(context, indent=2)

def create_function_definitions() -> List[Dict]:
    """Create OpenAI function definitions for available tasks."""
    return [
        {
            "type": "function",
            "function": {
                "name": "tail",
                "description": "Follow an enemy drone while maintaining a certain distance",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enemy_drone": {
                            "type": "string",
                            "description": "The ID of the enemy drone to tail (e.g., 'enemy_1')"
                        },
                        "friendly_drones": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of friendly drone IDs to use for tailing. If the user says 'closest', use the distances_to_enemies data from the world context to find the drone(s) with the smallest distance value for the specified enemy_drone."
                        }
                    },
                    "required": ["enemy_drone", "friendly_drones"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "patrol",
                "description": "Patrol between two or more locations in a loop",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "locations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                },
                                "required": ["x", "y"]
                            },
                            "description": "EXACTLY 2 locations to patrol between. REQUIRED: Must contain exactly 2 location objects with x and y coordinates. If the user provides chess notation (e.g., 'B4', 'D7'), you MUST convert each one to x,y coordinates using: column_index = (letter ASCII - 65), row_index = (number - 1), x = column_index * 100 + 50, y = row_index * 100 + 50. Example: 'B4' → column_index=1, row_index=3 → x=150, y=350 → {{'x': 150, 'y': 350}}"
                        },
                        "friendly_drones": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of friendly drone IDs to use for patrolling"
                        }
                    },
                    "required": ["locations", "friendly_drones"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "hold",
                "description": "Stop selected drones at their current positions",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "friendly_drones": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of friendly drone IDs to stop"
                        }
                    },
                    "required": ["friendly_drones"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "return_to_base",
                "description": "Send selected drones back to their home bases",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "friendly_drones": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of friendly drone IDs to send back to base"
                        }
                    },
                    "required": ["friendly_drones"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "intercept",
                "description": "Intercept an enemy drone by calculating the best intercept route based on the enemy's movement pattern. All drones will attempt to intercept, and once one succeeds, the others return to their starting positions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "enemy_drone": {
                            "type": "string",
                            "description": "The ID of the enemy drone to intercept (e.g., 'enemy_1')"
                        },
                        "friendly_drones": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of friendly drone IDs to use for intercepting. If the user says 'closest', use the distances_to_enemies data from the world context to find the drone(s) with the smallest distance value for the specified enemy_drone."
                        }
                    },
                    "required": ["enemy_drone", "friendly_drones"]
                }
            }
        }
    ]

@app.post("/nl/command")
async def process_natural_language(command: NaturalLanguageCommand):
    """Process natural language command using OpenAI."""
    global openai_client
    
    # Initialize OpenAI client if not already done
    if openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                "success": False,
                "message": "OpenAI API key not set. Please create a .env file with OPENAI_API_KEY=your_key"
            }
        try:
            openai_client = OpenAI(api_key=api_key)
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to initialize OpenAI client: {str(e)}"
            }
    
    # Get current world context
    world_context = get_world_context()
    
    # Create system prompt
    system_prompt = f"""You are a drone command assistant. You help users control drones using natural language.

CRITICAL: YOU MUST CALL EXACTLY ONE FUNCTION EXACTLY ONCE. NEVER CALL MULTIPLE FUNCTIONS. NEVER CALL THE SAME FUNCTION MULTIPLE TIMES. DO NOT PROVIDE TEXT EXPLANATIONS. DO NOT EXPLAIN YOUR REASONING IN TEXT. IMMEDIATELY CALL THE APPROPRIATE FUNCTION WITH THE CORRECT PARAMETERS IN A SINGLE FUNCTION CALL.

Current world state:
{world_context}

MAP GRID SYSTEM - COORDINATE CONVERSION:
The map uses a chess-style coordinate system with letters A-J (10 columns) and numbers 1-10 (10 rows).
Each cell is 100x100 pixels. The world is 1000x1000 pixels total.

STEP-BY-STEP COORDINATE CONVERSION (CRITICAL - FOLLOW EXACTLY):
To convert chess notation like "B4" to x,y coordinates, follow these steps:

1. Extract the letter and number:
   - "B4" → letter = "B", number = 4

2. Convert letter to column index:
   - A = 0, B = 1, C = 2, D = 3, E = 4, F = 5, G = 6, H = 7, I = 8, J = 9
   - Formula: column_index = (ASCII code of letter) - 65
   - Example: "B" = ASCII 66, so column_index = 66 - 65 = 1

3. Convert number to row index:
   - Number 1 = row 0, 2 = row 1, 3 = row 2, ..., 10 = row 9
   - Formula: row_index = number - 1
   - Example: 4 → row_index = 4 - 1 = 3

4. Calculate x coordinate (center of cell):
   - x = column_index * 100 + 50
   - Example: column_index 1 → x = 1 * 100 + 50 = 150

5. Calculate y coordinate (center of cell):
   - y = row_index * 100 + 50
   - Example: row_index 3 → y = 3 * 100 + 50 = 350

COMPLETE EXAMPLES:
- "A1": A=0, 1=0 → x=0*100+50=50, y=0*100+50=50 → {{"x": 50, "y": 50}}
- "B4": B=1, 4=3 → x=1*100+50=150, y=3*100+50=350 → {{"x": 150, "y": 350}}
- "D7": D=3, 7=6 → x=3*100+50=350, y=6*100+50=650 → {{"x": 350, "y": 650}}
- "J10": J=9, 10=9 → x=9*100+50=950, y=9*100+50=950 → {{"x": 950, "y": 950}}

When the user says coordinates like "Patrol B4 to D7", you MUST convert BOTH coordinates:
- "B4" → {{"x": 150, "y": 350}}
- "D7" → {{"x": 350, "y": 650}}
Then use both in the locations array: [{{"x": 150, "y": 350}}, {{"x": 350, "y": 650}}]

IMPORTANT: The world context includes a "closest_drones" object that PRE-CALCULATES all friendly drones sorted by distance for each enemy.
To find the closest drone(s) to a specific enemy (e.g., "enemy_4"):
- Look at closest_drones["enemy_4"]["closest_drones_sorted"] - this is an array of all friendly drone IDs sorted by distance (closest first)
- For "closest drone" (singular): use the FIRST element: closest_drones["enemy_4"]["closest_drones_sorted"][0]
- For "closest 3 drones" (plural): use the FIRST 3 elements: closest_drones["enemy_4"]["closest_drones_sorted"][0:3]
- You do NOT need to calculate anything - it's already sorted for you!

Example: If closest_drones["enemy_4"]["closest_drones_sorted"] = ["drone_12", "drone_6", "drone_9", ...], 
then "drone_12" is closest, "drone_6" is second closest, "drone_9" is third closest, etc.

Available functions:
- tail(enemy_drone, friendly_drones): Follow an enemy drone with one or more friendly drones
- patrol(locations, friendly_drones): Patrol between exactly 2 locations with one or more friendly drones. REQUIRES exactly 2 locations in the locations array.
- hold(friendly_drones): Stop selected drones at their current positions
- return_to_base(friendly_drones): Send selected drones back to their home bases
- intercept(enemy_drone, friendly_drones): Intercept an enemy drone using calculated intercept routes based on the enemy's movement pattern

CRITICAL RULES - READ CAREFULLY:
1. YOU MUST CALL EXACTLY ONE FUNCTION EXACTLY ONCE. NEVER CALL TWO OR MORE FUNCTIONS. NEVER CALL THE SAME FUNCTION TWICE.
2. NEVER RESPOND WITH TEXT ONLY. ALWAYS USE EXACTLY ONE TOOL CALL.
3. ONLY call the function that matches what the user requested:
   - If the user says "patrol" or "patrol from X to Y" → CALL patrol() EXACTLY ONCE
   - If the user says "tail" → CALL tail() EXACTLY ONCE
   - If the user says "hold" or "stop" → CALL hold() EXACTLY ONCE
   - If the user says "return to base" or "go home" → CALL return_to_base() EXACTLY ONCE
   - If the user says "intercept" → CALL intercept() EXACTLY ONCE
   - DO NOT call multiple different functions. DO NOT call the same function multiple times.
4. When calling a function, include ALL drones in a SINGLE call. DO NOT split into multiple calls.
5. To find the closest drone(s):
   - Use the "closest_drones" object in the world context
   - For enemy "enemy_X", look at closest_drones["enemy_X"]["closest_drones_sorted"]
   - This is an array of drone IDs sorted by distance (closest first)
   - For 1 drone: use [0] (first element)
   - For 3 drones: use [0:3] (first 3 elements)
   - For N drones: use [0:N] (first N elements)
6. DO NOT make multiple separate function calls. DO NOT call the function once per drone. DO NOT call the same function twice.
7. DO NOT EXPLAIN YOUR REASONING. DO NOT SHOW YOUR CALCULATIONS. JUST MAKE ONE SINGLE FUNCTION CALL.

Step-by-step examples (DO NOT EXPLAIN - JUST CALL THE FUNCTION):

Example 1: "Tail enemy drone 4 with my closest drone"
- Look at closest_drones["enemy_4"]["closest_drones_sorted"][0] → "drone_12"
- CALL: tail({{"enemy_drone": "enemy_4", "friendly_drones": ["drone_12"]}})

Example 2: "Tail enemy drone 4 with my 3 closest drones"
- Look at closest_drones["enemy_4"]["closest_drones_sorted"][0:3] → ["drone_12", "drone_6", "drone_9"]
- CALL: tail({{"enemy_drone": "enemy_4", "friendly_drones": ["drone_12", "drone_6", "drone_9"]}})

Example 3: "Stop my closest 3 drones" or "Hold my closest 3 drones"
- Use friendly_drones from world context (e.g., ["drone_1", "drone_2", "drone_3"])
- CALL: hold({{"friendly_drones": ["drone_1", "drone_2", "drone_3"]}})

Example 4: "Send my drones back to base" or "Return my drones to base"
- Use all friendly_drones from world context
- CALL: return_to_base({{"friendly_drones": ["drone_1", "drone_2", ...]}})

Example 5: "Intercept enemy drone 4 with my closest drone"
- Look at closest_drones["enemy_4"]["closest_drones_sorted"][0] → "drone_12"
- CALL: intercept({{"enemy_drone": "enemy_4", "friendly_drones": ["drone_12"]}})

Example 6: "Intercept enemy drone 4 with my 3 closest drones"
- Look at closest_drones["enemy_4"]["closest_drones_sorted"][0:3] → ["drone_12", "drone_6", "drone_9"]
- CALL: intercept({{"enemy_drone": "enemy_4", "friendly_drones": ["drone_12", "drone_6", "drone_9"]}})

Example 7: "Patrol from B4 to D7" or "Patrol B4 D7"
- Step 1: Convert "B4" to coordinates:
  * Letter "B": ASCII 66, column_index = 66 - 65 = 1
  * Number 4: row_index = 4 - 1 = 3
  * x = 1 * 100 + 50 = 150
  * y = 3 * 100 + 50 = 350
  * Result: {{"x": 150, "y": 350}}
- Step 2: Convert "D7" to coordinates:
  * Letter "D": ASCII 68, column_index = 68 - 65 = 3
  * Number 7: row_index = 7 - 1 = 6
  * x = 3 * 100 + 50 = 350
  * y = 6 * 100 + 50 = 650
  * Result: {{"x": 350, "y": 650}}
- CALL: patrol({{"locations": [{{"x": 150, "y": 350}}, {{"x": 350, "y": 650}}], "friendly_drones": ["drone_1"]}})

Example 8: "Patrol A1 to J10"
- "A1": A=0, 1=0 → x=50, y=50
- "J10": J=9, 10=9 → x=950, y=950
- CALL: patrol({{"locations": [{{"x": 50, "y": 50}}, {{"x": 950, "y": 950}}], "friendly_drones": ["drone_1"]}})

IMPORTANT: Patrol REQUIRES exactly 2 locations. If the user only provides one location, you MUST ask for clarification or infer a second location based on context. However, it's better to require both points explicitly.

Always use the exact drone IDs from closest_drones_sorted array. The array is pre-sorted - just take the first N elements!
When converting chess notation to coordinates, remember: A-J (10 letters), 1-10 (10 numbers), cell size is 100 pixels, coordinates are center of cell (column * 100 + 50, row * 100 + 50).

FINAL REMINDER: YOU MUST CALL EXACTLY ONE FUNCTION EXACTLY ONCE. NEVER TWO FUNCTIONS. NEVER THE SAME FUNCTION TWICE. DO NOT RESPOND WITH TEXT. DO NOT EXPLAIN. JUST MAKE ONE SINGLE FUNCTION CALL IMMEDIATELY.
"""
    
    try:
        # Call OpenAI API in a thread pool to avoid blocking the event loop
        # This prevents the simulation from freezing during the API call
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": command.command}
                ],
                tools=create_function_definitions(),
                tool_choice="auto",
                temperature=0.1  # Lower temperature for more deterministic, accurate responses
            )
        )
        
        message = response.choices[0].message
        
        # Check if function was called
        if message.tool_calls:
            # CRITICAL: Only process the FIRST tool call if multiple are returned
            # This ensures we only execute one function per command
            if len(message.tool_calls) > 1:
                print(f"Warning: LLM returned {len(message.tool_calls)} tool calls, but only processing the first one")
            
            # Process only the first tool call
            tool_call = message.tool_calls[0]
            function_name = tool_call.function.name
            results = []
            
            try:
                function_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "message": f"Failed to parse function arguments: {str(e)}"
                }
            
            # Execute the function
            if function_name in TASK_FUNCTIONS:
                try:
                    task_func = TASK_FUNCTIONS[function_name]
                    result = task_func(**function_args)
                    results.append({
                        "success": True,
                        "task_name": result["task_name"],
                        "parameters": result["parameters"]
                    })
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"Error executing {function_name}: {str(e)}"
                    }
            else:
                return {
                    "success": False,
                    "message": f"Unknown function: {function_name}"
                }
            
            # Format tool call for display (only the first one)
            tool_calls_display = []
            try:
                function_args = json.loads(tool_call.function.arguments)
                tool_calls_display.append({
                    "function": tool_call.function.name,
                    "arguments": function_args
                })
            except:
                pass
            
            return {
                "success": True,
                "message": f"Processed command: {command.command}",
                "results": results,
                "tool_calls": tool_calls_display,  # Include tool calls for chatbot display
                "debug": {
                    "world_context": json.loads(world_context)  # Include world context in response for debugging
                }
            }
        else:
            # No function was called - LLM might have responded with text
            if message.content:
                return {
                    "success": False,
                    "message": f"LLM response: {message.content}. Could not parse as command. Please try rephrasing."
                }
            return {
                "success": False,
                "message": "Could not parse command. Please try rephrasing."
            }
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error processing NL command: {error_details}")  # Log to console for debugging
        return {
            "success": False,
            "message": f"Error processing command: {str(e)}"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

