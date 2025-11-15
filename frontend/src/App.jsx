import React, { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'
const POLL_INTERVAL = 50 // ms (20 updates per second for smooth UI)

function App() {
  const [drones, setDrones] = useState([])
  const [selectedDrones, setSelectedDrones] = useState(new Set())
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState(null)
  const [dragEnd, setDragEnd] = useState(null)
  const dragShiftKey = useRef(false)
  const dragStartSelection = useRef(new Set())
  const justFinishedDrag = useRef(false)
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

  // Convert screen coordinates to world coordinates using SVG's native transformation
  const screenToWorld = useCallback((screenX, screenY) => {
    if (!svgRef.current) return { x: 0, y: 0 }
    const svg = svgRef.current
    const pt = svg.createSVGPoint()
    pt.x = screenX
    pt.y = screenY
    const svgPoint = pt.matrixTransform(svg.getScreenCTM().inverse())
    return {
      x: svgPoint.x,
      y: svgPoint.y
    }
  }, [])

  // Handle click on map (move selected drones)
  const handleMapClick = useCallback(async (e) => {
    // Don't move drones if we just finished a drag operation
    if (justFinishedDrag.current) {
      justFinishedDrag.current = false
      return
    }
    
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

  // Handle click on drone (select, or add to selection with shift)
  const handleDroneClick = useCallback((e, droneId) => {
    e.stopPropagation()
    setSelectedDrones(prev => {
      if (e.shiftKey) {
        // Shift+click: toggle this drone in selection
        const next = new Set(prev)
        if (next.has(droneId)) {
          next.delete(droneId)
        } else {
          next.add(droneId)
        }
        return next
      } else {
        // Regular click: select only this drone
        return new Set([droneId])
      }
    })
  }, [])

  // Selection box drag handlers
  const handleMouseDown = useCallback((e) => {
    // Only start dragging if clicking on the map background (not on a drone or selection box)
    const target = e.target
    const isBackground = target === svgRef.current || 
                         target.tagName === 'rect' ||
                         target.tagName === 'path'
    const isSelectionBox = target.getAttribute && 
                          (target.getAttribute('fill') === 'rgba(0, 150, 255, 0.2)' ||
                           target.getAttribute('stroke') === 'rgba(0, 150, 255, 0.8)')
    const isDrone = target.tagName === 'circle' || target.tagName === 'g' || target.tagName === 'text'
    
    if (isBackground && !isSelectionBox && !isDrone) {
      // Don't prevent default - let click handler work if it's just a click
      // Only start tracking for potential drag if mouse moves
      dragShiftKey.current = e.shiftKey
      // Preserve the starting selection (we'll clear it only if we actually drag)
      dragStartSelection.current = new Set(selectedDrones)
      const worldPos = screenToWorld(e.clientX, e.clientY)
      setDragStart(worldPos)
      setDragEnd(worldPos)
      // Don't clear selection yet - wait to see if it's a drag or click
    }
  }, [screenToWorld, selectedDrones])

  const handleMouseMove = useCallback((e) => {
    if (dragStart) {
      const worldPos = screenToWorld(e.clientX, e.clientY)
      const distance = Math.sqrt(
        Math.pow(worldPos.x - dragStart.x, 2) + 
        Math.pow(worldPos.y - dragStart.y, 2)
      )
      
      // Only start showing selection box if mouse moved more than 5 pixels
      if (distance > 5) {
        if (!isDragging) {
          setIsDragging(true)
          // Now that we're actually dragging, clear selection if shift not held
          // (Shift+drag will add to existing selection)
          if (!dragShiftKey.current) {
            setSelectedDrones(new Set())
          }
        }
        setDragEnd(worldPos)
      }
    }
  }, [isDragging, dragStart, screenToWorld])

  const handleMouseUp = useCallback(() => {
    if (isDragging && dragStart && dragEnd) {
      // We actually dragged - create selection box
      const minX = Math.min(dragStart.x, dragEnd.x)
      const maxX = Math.max(dragStart.x, dragEnd.x)
      const minY = Math.min(dragStart.y, dragEnd.y)
      const maxY = Math.max(dragStart.y, dragEnd.y)

      // Add drones in box to selection (or replace if shift not held)
      // Use the preserved starting selection if shift was held
      const newSelection = dragShiftKey.current ? new Set(dragStartSelection.current) : new Set()
      drones.forEach(drone => {
        // Only select friendly drones
        if (drone.team === "friendly" &&
            drone.x >= minX && drone.x <= maxX && 
            drone.y >= minY && drone.y <= maxY) {
          newSelection.add(drone.id)
        }
      })
      setSelectedDrones(newSelection)
      
      // Mark that we just finished a drag to prevent click handler from firing
      justFinishedDrag.current = true
      setTimeout(() => {
        justFinishedDrag.current = false
      }, 100)
    } else if (dragStart && dragEnd) {
      // Check if it was a small movement (should be treated as click)
      const dragDistance = Math.sqrt(
        Math.pow(dragEnd.x - dragStart.x, 2) + 
        Math.pow(dragEnd.y - dragStart.y, 2)
      )
      if (dragDistance < 5) {
        // Very small movement, treat as click - allow click handler to fire
        justFinishedDrag.current = false
      } else {
        // Some movement but not enough to trigger drag - still prevent click
        justFinishedDrag.current = true
        setTimeout(() => {
          justFinishedDrag.current = false
        }, 100)
      }
    }
    setIsDragging(false)
    setDragStart(null)
    setDragEnd(null)
  }, [isDragging, dragStart, dragEnd, drones, selectedDrones])

  useEffect(() => {
    // Always listen for mouse move and up when we have a drag start
    // This allows us to detect if it's a click vs drag
    if (dragStart !== null) {
      window.addEventListener('mousemove', handleMouseMove)
      window.addEventListener('mouseup', handleMouseUp)
      return () => {
        window.removeEventListener('mousemove', handleMouseMove)
        window.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [dragStart, handleMouseMove, handleMouseUp])

  // Handle ESC key to deselect all drones
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSelectedDrones(new Set())
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

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
          <span>Friendly: {drones.filter(d => d.team === 'friendly').length}</span>
          <span>Enemy: {drones.filter(d => d.team === 'enemy').length}</span>
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
              pointerEvents="none"
            />
          )}

          {/* Drones */}
          {drones.map(drone => {
            const isFriendly = drone.team === "friendly"
            const isSelected = isFriendly && selectedDrones.has(drone.id)
            
            // Color scheme: friendly = blue, enemy = red
            const colors = isFriendly ? {
              fill: isSelected ? "#00aaff" : "#0088ff",
              stroke: isSelected ? "#ffffff" : "#0066cc",
            } : {
              fill: "#ff4444",
              stroke: "#cc0000",
            }
            
            return (
              <g
                key={drone.id}
                onClick={isFriendly ? (e) => handleDroneClick(e, drone.id) : undefined}
                style={{ cursor: isFriendly ? 'pointer' : 'default' }}
              >
                {/* Drone circle */}
                <circle
                  cx={drone.x}
                  cy={drone.y}
                  r={isSelected ? 12 : 10}
                  fill={colors.fill}
                  stroke={colors.stroke}
                  strokeWidth={isSelected ? 3 : 2}
                  className="drone"
                />
                {/* Drone ID label (only for friendly drones) */}
                {isFriendly && (
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
                )}
                {/* Target indicator (only for friendly drones) */}
                {isFriendly && drone.mode === "moving" && drone.target_x !== null && drone.target_y !== null && (
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
        <p>Click drone to select • Drag box to select multiple • Click map to move • ESC to deselect</p>
      </div>
    </div>
  )
}

export default App

