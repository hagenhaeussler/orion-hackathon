import React, { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'
const POLL_INTERVAL = 250 // ms

function App() {
  const [drones, setDrones] = useState([])
  const [selectedDrones, setSelectedDrones] = useState(new Set())
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState(null)
  const [dragEnd, setDragEnd] = useState(null)
  const svgRef = useRef(null)
  const worldWidth = 1000
  const worldHeight = 1000

  // Poll backend for world state
  useEffect(() => {
    const fetchWorld = async () => {
      try {
        const response = await fetch(`${API_BASE}/world`)
        const data = await response.json()
        setDrones(data.drones || [])
      } catch (error) {
        console.error('Failed to fetch world state:', error)
      }
    }

    fetchWorld()
    const interval = setInterval(fetchWorld, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [])

  // Convert screen coordinates to world coordinates
  const screenToWorld = useCallback((screenX, screenY) => {
    if (!svgRef.current) return { x: 0, y: 0 }
    const svg = svgRef.current
    const rect = svg.getBoundingClientRect()
    const scaleX = worldWidth / rect.width
    const scaleY = worldHeight / rect.height
    return {
      x: (screenX - rect.left) * scaleX,
      y: (screenY - rect.top) * scaleY
    }
  }, [worldWidth, worldHeight])

  // Handle click on map (move selected drones)
  const handleMapClick = useCallback(async (e) => {
    if (selectedDrones.size === 0) return

    const worldPos = screenToWorld(e.clientX, e.clientY)
    
    try {
      const response = await fetch(`${API_BASE}/command`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          drone_ids: Array.from(selectedDrones),
          target_x: worldPos.x,
          target_y: worldPos.y
        })
      })
      
      if (!response.ok) {
        console.error('Failed to send command')
      }
    } catch (error) {
      console.error('Error sending command:', error)
    }
  }, [selectedDrones, screenToWorld])

  // Handle click on drone (toggle selection)
  const handleDroneClick = useCallback((e, droneId) => {
    e.stopPropagation()
    setSelectedDrones(prev => {
      const next = new Set(prev)
      if (next.has(droneId)) {
        next.delete(droneId)
      } else {
        next.add(droneId)
      }
      return next
    })
  }, [])

  // Selection box drag handlers
  const handleMouseDown = useCallback((e) => {
    if (e.target === svgRef.current || e.target.tagName === 'rect') {
      setIsDragging(true)
      const worldPos = screenToWorld(e.clientX, e.clientY)
      setDragStart(worldPos)
      setDragEnd(worldPos)
      
      // Clear selection if not holding shift
      if (!e.shiftKey) {
        setSelectedDrones(new Set())
      }
    }
  }, [screenToWorld])

  const handleMouseMove = useCallback((e) => {
    if (isDragging && dragStart) {
      const worldPos = screenToWorld(e.clientX, e.clientY)
      setDragEnd(worldPos)
    }
  }, [isDragging, dragStart, screenToWorld])

  const handleMouseUp = useCallback(() => {
    if (isDragging && dragStart && dragEnd) {
      // Select drones in selection box
      const minX = Math.min(dragStart.x, dragEnd.x)
      const maxX = Math.max(dragStart.x, dragEnd.x)
      const minY = Math.min(dragStart.y, dragEnd.y)
      const maxY = Math.max(dragStart.y, dragEnd.y)

      const newSelection = new Set(selectedDrones)
      drones.forEach(drone => {
        if (drone.x >= minX && drone.x <= maxX && 
            drone.y >= minY && drone.y <= maxY) {
          newSelection.add(drone.id)
        }
      })
      setSelectedDrones(newSelection)
    }
    setIsDragging(false)
    setDragStart(null)
    setDragEnd(null)
  }, [isDragging, dragStart, dragEnd, drones, selectedDrones])

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      return () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [isDragging, handleMouseMove, handleMouseUp])

  // Calculate selection box coordinates
  const selectionBox = isDragging && dragStart && dragEnd ? {
    x: Math.min(dragStart.x, dragEnd.x),
    y: Math.min(dragStart.y, dragEnd.y),
    width: Math.abs(dragEnd.x - dragStart.x),
    height: Math.abs(dragEnd.y - dragStart.y)
  } : null

  return (
    <div className="app">
      <div className="header">
        <h1>Drone Swarm Control</h1>
        <div className="info">
          <span>Drones: {drones.length}</span>
          <span>Selected: {selectedDrones.size}</span>
        </div>
      </div>
      <div className="map-container">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${worldWidth} ${worldHeight}`}
          className="map"
          onClick={handleMapClick}
          onMouseDown={handleMouseDown}
        >
          {/* Grid background */}
          <defs>
            <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#333" strokeWidth="1"/>
            </pattern>
          </defs>
          <rect width={worldWidth} height={worldHeight} fill="#0a0a0a" />
          <rect width={worldWidth} height={worldHeight} fill="url(#grid)" />
          
          {/* Selection box */}
          {selectionBox && (
            <rect
              x={selectionBox.x}
              y={selectionBox.y}
              width={selectionBox.width}
              height={selectionBox.height}
              fill="rgba(0, 150, 255, 0.2)"
              stroke="rgba(0, 150, 255, 0.8)"
              strokeWidth="2"
              strokeDasharray="5,5"
            />
          )}

          {/* Drones */}
          {drones.map(drone => {
            const isSelected = selectedDrones.has(drone.id)
            return (
              <g
                key={drone.id}
                onClick={(e) => handleDroneClick(e, drone.id)}
                style={{ cursor: 'pointer' }}
              >
                {/* Drone circle */}
                <circle
                  cx={drone.x}
                  cy={drone.y}
                  r={isSelected ? 12 : 10}
                  fill={isSelected ? "#00aaff" : "#00ff88"}
                  stroke={isSelected ? "#ffffff" : "#00cc66"}
                  strokeWidth={isSelected ? 3 : 2}
                  className="drone"
                />
                {/* Drone ID label */}
                <text
                  x={drone.x}
                  y={drone.y - 18}
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="10"
                  fontWeight="bold"
                  pointerEvents="none"
                >
                  {drone.id.replace('drone_', '')}
                </text>
                {/* Target indicator */}
                {drone.mode === "moving" && drone.target_x !== null && drone.target_y !== null && (
                  <g>
                    <circle
                      cx={drone.target_x}
                      cy={drone.target_y}
                      r="5"
                      fill="none"
                      stroke="#ffaa00"
                      strokeWidth="2"
                      strokeDasharray="3,3"
                    />
                    <line
                      x1={drone.x}
                      y1={drone.y}
                      x2={drone.target_x}
                      y2={drone.target_y}
                      stroke="#ffaa00"
                      strokeWidth="1"
                      strokeDasharray="2,2"
                      opacity="0.5"
                    />
                  </g>
                )}
              </g>
            )
          })}
        </svg>
      </div>
      <div className="instructions">
        <p>Click and drag to select drones • Click on map to move selected drones</p>
      </div>
    </div>
  )
}

export default App

