import React, { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'
const POLL_INTERVAL = 50 // ms (20 updates per second for smooth UI)

function App() {
  const [drones, setDrones] = useState([])
  const [selectedDrones, setSelectedDrones] = useState(new Set())
  const [bases, setBases] = useState({})
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState(null)
  const [dragEnd, setDragEnd] = useState(null)
  const dragShiftKey = useRef(false)
  const dragStartSelection = useRef(new Set())
  const justFinishedDrag = useRef(false)
  const svgRef = useRef(null)
  const worldWidth = 1000
  const worldHeight = 1000
  
  // Mode state
  const [patrolMode, setPatrolMode] = useState(false)  // Track if waiting for patrol target click
  const [tailMode, setTailMode] = useState(false)  // Track if waiting for enemy drone selection
  
  // Time control state
  const [isPaused, setIsPaused] = useState(false)
  const [isReversing, setIsReversing] = useState(false)
  
  // Fog of war state
  const [fogOfWarEnabled, setFogOfWarEnabled] = useState(false)
  const FOG_VISION_RADIUS = 200  // Radius around friendly drones where we can see
  const FOG_VISIBILITY_RADIUS = 250  // Larger radius for map visibility
  
  // Task system state
  const [showTaskMenu, setShowTaskMenu] = useState(false)
  const [taskMenuDrone, setTaskMenuDrone] = useState(null)
  const [taskMenuPosition, setTaskMenuPosition] = useState({ x: 0, y: 0 })
  const [availableTasks, setAvailableTasks] = useState({})
  const [selectedTask, setSelectedTask] = useState("")
  const [taskParams, setTaskParams] = useState({})
  const [nlCommand, setNlCommand] = useState("")
  const [nlOutputs, setNlOutputs] = useState([])  // Store all parsed command outputs
  const [taskResults, setTaskResults] = useState([])
  
  // Format tool call as Python function call
  const formatPythonCall = (toolCall) => {
    const funcName = toolCall.function || toolCall.function_name || ''
    const args = toolCall.arguments || toolCall.parameters || {}
    
    // Format arguments as key=value pairs
    const argPairs = Object.entries(args)
      .filter(([key]) => key !== 'distance') // Remove distance parameter
      .map(([key, value]) => {
        if (Array.isArray(value)) {
          return `${key}=[${value.map(v => typeof v === 'string' ? v : JSON.stringify(v)).join(', ')}]`
        } else if (typeof value === 'string') {
          return `${key}=${value}`
        } else {
          return `${key}=${JSON.stringify(value)}`
        }
      })
    
    return `${funcName}(${argPairs.join(', ')})`
  }

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

  // Fetch bases on mount
  useEffect(() => {
    const fetchBases = async () => {
      try {
        const response = await fetch(`${API_BASE}/bases`)
        const data = await response.json()
        setBases(data.bases || {})
      } catch (error) {
        console.error('Failed to fetch bases:', error)
      }
    }
    fetchBases()
  }, [])

  // Fetch available tasks
  useEffect(() => {
    const fetchTasks = async () => {
      try {
        const response = await fetch(`${API_BASE}/tasks`)
        const data = await response.json()
        setAvailableTasks(data.tasks || {})
      } catch (error) {
        console.error('Failed to fetch tasks:', error)
      }
    }
    fetchTasks()
  }, [])

  // Poll for task results
  useEffect(() => {
    const fetchResults = async () => {
      try {
        const response = await fetch(`${API_BASE}/task/results`)
        const data = await response.json()
        setTaskResults(data.results || [])
      } catch (error) {
        console.error('Failed to fetch task results:', error)
      }
    }
    fetchResults()
    const interval = setInterval(fetchResults, 500) // Poll every 500ms
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

  // Handle click on map (move selected drones or set patrol target)
  const handleMapClick = useCallback(async (e) => {
    // Don't move drones if we just finished a drag operation
    if (justFinishedDrag.current) {
      justFinishedDrag.current = false
      return
    }
    
    if (selectedDrones.size === 0) return

    const worldPos = screenToWorld(e.clientX, e.clientY)
    
    try {
      // Check if we're in patrol mode
      if (patrolMode) {
        // Send patrol command
        const firstDrone = drones.find(d => selectedDrones.has(d.id))
        const response = await fetch(`${API_BASE}/task/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            task_name: "patrol",
            drone_ids: Array.from(selectedDrones),
            parameters: {
              friendly_drones: Array.from(selectedDrones),
              locations: [
                { x: firstDrone?.x || worldPos.x, y: firstDrone?.y || worldPos.y },
                { x: worldPos.x, y: worldPos.y }
              ]
            }
          })
        })
        
        if (!response.ok) {
          console.error('Failed to send patrol command')
        }
        
        // Exit patrol mode
        setPatrolMode(false)
      } else {
        // Normal move command
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
      }
    } catch (error) {
      console.error('Error sending command:', error)
    }
    // Don't hide action panel when clicking on map - it's always visible now
  }, [selectedDrones, screenToWorld, patrolMode, drones])

  // Handle click on drone (select, or add to selection with shift, or target for tail mode)
  const handleDroneClick = useCallback(async (e, droneId) => {
    e.stopPropagation()
    
    const drone = drones.find(d => d.id === droneId)
    if (!drone) return
    
    // If in tail mode and clicked on enemy drone, send tail command
    if (tailMode && drone.team === 'enemy') {
      if (selectedDrones.size === 0) {
        setTailMode(false)
        return
      }
      
      try {
        const response = await fetch(`${API_BASE}/task/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            task_name: "tail",
            drone_ids: Array.from(selectedDrones),
            parameters: {
              enemy_drone: droneId,
              friendly_drones: Array.from(selectedDrones)
            }
          })
        })
        
        if (!response.ok) {
          console.error('Failed to send tail command')
        }
      } catch (error) {
        console.error('Error sending tail command:', error)
      }
      
      setTailMode(false)
      return
    }
    
    // Normal selection logic for friendly drones
    if (drone.team === 'friendly') {
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
    }
  }, [tailMode, selectedDrones, drones])

  // Handle task execution via UI
  const handleExecuteTask = useCallback(async () => {
    if (!selectedTask || !taskMenuDrone) return
    
    const params = {
      friendly_drones: Array.from(selectedDrones.size > 0 ? selectedDrones : new Set([taskMenuDrone.id])),
      ...taskParams
    }
    
    try {
      const response = await fetch(`${API_BASE}/task/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_name: selectedTask,
          drone_ids: params.friendly_drones,
          parameters: params
        })
      })
      const data = await response.json()
      if (data.success) {
        setShowTaskMenu(false)
        setSelectedTask("")
        setTaskParams({})
      }
    } catch (error) {
      console.error('Failed to execute task:', error)
    }
  }, [selectedTask, taskMenuDrone, selectedDrones, taskParams])

  // Handle natural language command
  const handleNlCommand = useCallback(async () => {
    if (!nlCommand.trim()) return
    
    const commandText = nlCommand.trim()
    setNlCommand("")  // Clear input immediately
    
    try {
      const response = await fetch(`${API_BASE}/nl/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: commandText })
      })
      const data = await response.json()
      if (data.success) {
        // Store the parsed output for display (append to array)
        if (data.tool_calls && data.tool_calls.length > 0) {
          setNlOutputs(prev => [...prev, { tool_calls: data.tool_calls, originalCommand: commandText }])
        } else if (data.results && data.results.length > 0) {
          // Fallback to results if tool_calls not available
          setNlOutputs(prev => [...prev, { results: data.results, originalCommand: commandText }])
        }
        // Debug: Log world context to browser console
        if (data.debug && data.debug.world_context) {
          console.log('World Context (for debugging):', JSON.stringify(data.debug.world_context, null, 2))
        }
      } else {
        console.error('NL command error:', data)
        setNlOutputs(prev => [...prev, { error: data.message, originalCommand: commandText }])
      }
    } catch (error) {
      console.error('Failed to process natural language command:', error)
      setNlOutputs(prev => [...prev, { error: error.message, originalCommand: commandText }])
    }
  }, [nlCommand])

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

  // Right-click (context menu) on a drone
  const handleDroneContextMenu = useCallback((e, drone) => {
    if (drone.team !== 'friendly') return
    e.preventDefault()
    e.stopPropagation()
    // Keep current selection, but ensure right-clicked drone is included
    setSelectedDrones(prev => {
      const next = new Set(prev)
      if (!next.has(drone.id)) next.add(drone.id)
      return next
    })
  }, [])

  // Right-click anywhere on map
  const handleMapContextMenu = useCallback((e) => {
    e.preventDefault()
    e.stopPropagation()
    // Could open context menu here in the future
  }, [])

  // Toggle drone selection from checkbox
  const toggleDroneSelection = useCallback((droneId) => {
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

  // Stop / hold selected drones
  const stopSelectedDrones = useCallback(async () => {
    if (selectedDrones.size === 0) return
    try {
      const response = await fetch(`${API_BASE}/task/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_name: "hold",
          drone_ids: Array.from(selectedDrones),
          parameters: {
            friendly_drones: Array.from(selectedDrones)
          }
        })
      })
      if (!response.ok) console.error('Failed to send hold command')
    } catch (err) {
      console.error('Error sending hold command:', err)
    }

    // Control panel stays visible - just executed the command
  }, [selectedDrones])

  // Start patrol mode - wait for user to click target on map
  const startPatrolMode = useCallback(() => {
    if (selectedDrones.size === 0) return
    setPatrolMode(true)
  }, [selectedDrones])

  // Start tail mode - wait for user to click enemy drone
  const startTailMode = useCallback(() => {
    if (selectedDrones.size === 0) return
    setTailMode(true)
  }, [selectedDrones])

  // Return selected drones to their bases
  const returnToBase = useCallback(async () => {
    if (selectedDrones.size === 0) return
    try {
      const response = await fetch(`${API_BASE}/task/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_name: "return_to_base",
          drone_ids: Array.from(selectedDrones),
          parameters: {
            friendly_drones: Array.from(selectedDrones)
          }
        })
      })
      if (!response.ok) console.error('Failed to send return to base command')
    } catch (err) {
      console.error('Error sending return to base command:', err)
    }
    // Control panel stays visible
  }, [selectedDrones])

  // Set new base for selected drones
  const setDroneBase = useCallback(async (baseId) => {
    if (selectedDrones.size === 0) return
    try {
      const response = await fetch(`${API_BASE}/set-base`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          drone_ids: Array.from(selectedDrones),
          base_id: baseId
        })
      })
      if (!response.ok) console.error('Failed to set base')
    } catch (err) {
      console.error('Error setting base:', err)
    }
  }, [selectedDrones])

  // When deselecting, just uncheck all boxes (don't clear action panel)
  useEffect(() => {
    // This effect ensures that when selectedDrones becomes empty, 
    // all checkboxes will be unchecked (they're controlled by selectedDrones.has())
  }, [selectedDrones])

  // Toggle pause
  const togglePause = useCallback(async () => {
    const newPausedState = !isPaused
    setIsPaused(newPausedState)
    try {
      await fetch(`${API_BASE}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused: newPausedState })
      })
    } catch (err) {
      console.error('Error toggling pause:', err)
    }
  }, [isPaused])

  // Toggle reverse time
  const toggleReverse = useCallback(async () => {
    const newReverseState = !isReversing
    setIsReversing(newReverseState)
    try {
      const action = newReverseState ? 'reverse' : 'forward'
      await fetch(`${API_BASE}/time-control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      })
    } catch (err) {
      console.error('Error toggling reverse:', err)
    }
  }, [isReversing])

  // Reset simulation
  const resetSimulation = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      const data = await response.json()
      if (data.status === 'ok') {
        // Clear selections and reset states
        setSelectedDrones(new Set())
        setIsPaused(false)
        setIsReversing(false)
        setPatrolMode(false)
        setTailMode(false)
        setNlOutputs([])  // Clear command history on reset
      } else {
        console.warn(data.message || 'Failed to reset simulation')
      }
    } catch (err) {
      console.error('Error resetting simulation:', err)
    }
  }, [])

  // Handle ESC key to deselect all drones and close task menu
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSelectedDrones(new Set())  // Just uncheck all boxes
        setShowTaskMenu(false)
        setPatrolMode(false)  // Cancel patrol mode
        setTailMode(false)  // Cancel tail mode
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  // Close task menu when clicking outside
  useEffect(() => {
    if (showTaskMenu) {
      const handleClickOutside = (e) => {
        if (!e.target.closest('.task-menu')) {
          setShowTaskMenu(false)
        }
      }
      window.addEventListener('click', handleClickOutside)
      return () => {
        window.removeEventListener('click', handleClickOutside)
      }
    }
  }, [showTaskMenu])

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
        <div className="header-controls">
          {/* Fog of War Toggle */}
          <div className="fog-toggle">
            <label>
              <input
                type="checkbox"
                checked={fogOfWarEnabled}
                onChange={(e) => setFogOfWarEnabled(e.target.checked)}
              />
              <span>Fog of War</span>
            </label>
          </div>

          {/* Time Control Buttons */}
          <div className="time-controls">
            {/* Pause Button */}
            <button 
              className="pause-button" 
              onClick={togglePause}
              title={isPaused ? "Resume" : "Pause"}
            >
              {isPaused ? (
                <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <polygon points="8,5 19,12 8,19" fill="currentColor"/>
                </svg>
              ) : (
                <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <rect x="6" y="4" width="4" height="16" fill="currentColor"/>
                  <rect x="14" y="4" width="4" height="16" fill="currentColor"/>
                </svg>
              )}
            </button>
            
            {/* Reverse Time Button */}
            <button 
              className={`reverse-button ${isReversing ? 'active' : ''}`}
              onClick={toggleReverse}
              title={isReversing ? "Resume Forward" : "Reverse Time"}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                {/* Rewind icon: two backward-facing triangles (media player style) */}
                <polygon points="11,18 4,12 11,6" fill="currentColor"/>
                <polygon points="20,18 13,12 20,6" fill="currentColor"/>
              </svg>
            </button>
            
            {/* Reset Button */}
            <button 
              className="reset-button"
              onClick={resetSimulation}
              title="Reset Simulation"
            >
              <svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                {/* Reset icon: solid circular refresh arrow to match other icons */}
                <path d="M12 6V2l-4 4 4 4V8c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z" fill="currentColor"/>
              </svg>
            </button>
          </div>
        </div>
        <div className="info">
          <span>Friendly: {drones.filter(d => d.team === 'friendly').length}</span>
          <span>Enemy: {drones.filter(d => d.team === 'enemy').length}</span>
          <span>Selected: {selectedDrones.size}</span>
        </div>
      </div>
      <div className="main-layout">
        {/* Left: Chat Tab */}
        <div className="chat-tab">
          <div className="chat-tab-header">
            <h3>💬 Natural Language Command Chat</h3>
          </div>
          <div className="chat-tab-content">
            <div className="chat-output">
              {nlOutputs.length > 0 ? (
                nlOutputs.map((output, index) => (
                  <div key={index} className="nl-output-item">
                    <div className="nl-output-label">Command {index + 1}:</div>
                    {output.error ? (
                      <div className="nl-output-error">{output.error}</div>
                    ) : output.tool_calls ? (
                      <div className="nl-output-code">
                        {output.tool_calls.map((toolCall, i) => (
                          <div key={i}>{formatPythonCall(toolCall)}</div>
                        ))}
                      </div>
                    ) : output.results ? (
                      <div className="nl-output-code">
                        {output.results.map((result, i) => (
                          <div key={i}>{JSON.stringify(result)}</div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="nl-output-placeholder">
                  Enter a natural language command below to see the parsed commands here.
                </div>
              )}
            </div>
            <div className="chat-input-container">
              <input
                type="text"
                value={nlCommand}
                onChange={(e) => setNlCommand(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleNlCommand()}
                placeholder="e.g., 'Tail enemy drone 1 with my three closest drones'"
                className="chat-input"
              />
              <button onClick={handleNlCommand} className="chat-send-button">
                Send
              </button>
            </div>
          </div>
        </div>

        {/* Center: Map Grid */}
        <div className="map-container" onContextMenu={handleMapContextMenu}>
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
          
          {/* Geographic Features - Background Terrain */}
          {/* Mountains */}
          <g opacity="0.3">
            <polygon points="150,300 200,200 250,300" fill="#555" stroke="#666" strokeWidth="2"/>
            <polygon points="180,300 200,250 220,300" fill="#666" stroke="#777" strokeWidth="1"/>
            <polygon points="350,150 420,50 490,150" fill="#555" stroke="#666" strokeWidth="2"/>
            <polygon points="380,150 420,80 460,150" fill="#666" stroke="#777" strokeWidth="1"/>
            <polygon points="750,400 820,300 890,400" fill="#555" stroke="#666" strokeWidth="2"/>
            <polygon points="780,400 820,330 860,400" fill="#666" stroke="#777" strokeWidth="1"/>
          </g>
          
          {/* Rivers/Water */}
          <g opacity="0.4">
            <path 
              d="M 0,500 Q 200,480 400,500 T 800,520 L 1000,530" 
              fill="none" 
              stroke="#0066aa" 
              strokeWidth="25"
            />
            <path 
              d="M 0,500 Q 200,480 400,500 T 800,520 L 1000,530" 
              fill="none" 
              stroke="#0088cc" 
              strokeWidth="15"
            />
          </g>
          
          {/* Forests */}
          <g opacity="0.25">
            <circle cx="600" cy="200" r="60" fill="#1a4d1a"/>
            <circle cx="630" cy="180" r="50" fill="#1a4d1a"/>
            <circle cx="570" cy="180" r="45" fill="#1a4d1a"/>
            <circle cx="600" cy="230" r="40" fill="#1a4d1a"/>
            
            <circle cx="100" cy="700" r="70" fill="#1a4d1a"/>
            <circle cx="140" cy="720" r="55" fill="#1a4d1a"/>
            <circle cx="80" cy="750" r="50" fill="#1a4d1a"/>
            
            <circle cx="850" cy="650" r="65" fill="#1a4d1a"/>
            <circle cx="880" cy="680" r="50" fill="#1a4d1a"/>
            <circle cx="820" cy="690" r="45" fill="#1a4d1a"/>
          </g>
          
          {/* Rocky areas */}
          <g opacity="0.2">
            <ellipse cx="300" cy="750" rx="80" ry="60" fill="#444"/>
            <ellipse cx="320" cy="730" rx="40" ry="30" fill="#555"/>
            <ellipse cx="280" cy="770" rx="35" ry="25" fill="#555"/>
            
            <ellipse cx="700" cy="100" rx="70" ry="50" fill="#444"/>
            <ellipse cx="720" cy="90" rx="35" ry="25" fill="#555"/>
          </g>
          
          {/* Bases */}
          {Object.entries(bases).map(([baseId, base]) => {
            const size = 50
            return (
              <g key={baseId}>
                {base.shape === 'circle' && (
                  <circle
                    cx={base.x}
                    cy={base.y}
                    r={size}
                    fill="#2a2a2a"
                    stroke="#00ff88"
                    strokeWidth="3"
                  />
                )}
                {base.shape === 'square' && (
                  <rect
                    x={base.x - size}
                    y={base.y - size}
                    width={size * 2}
                    height={size * 2}
                    fill="#2a2a2a"
                    stroke="#00ff88"
                    strokeWidth="3"
                  />
                )}
                {base.shape === 'triangle' && (
                  <polygon
                    points={`${base.x},${base.y - size} ${base.x + size},${base.y + size} ${base.x - size},${base.y + size}`}
                    fill="#2a2a2a"
                    stroke="#00ff88"
                    strokeWidth="3"
                  />
                )}
                <text
                  x={base.x}
                  y={base.y + 70}
                  textAnchor="middle"
                  fill="#00ff88"
                  fontSize="14"
                  fontWeight="bold"
                >
                  {base.name}
                </text>
              </g>
            )
          })}
          
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
            
            // Check if enemy drone is visible (within vision radius of any friendly drone or base)
            // Only apply visibility check when fog of war is enabled
            // Use FOG_VISIBILITY_RADIUS to match the fog mask radius
            let isVisible = true
            if (!isFriendly && fogOfWarEnabled) {
              // Check if within range of any friendly drone
              const withinFriendlyRange = drones
                .filter(d => d.team === "friendly")
                .some(friendlyDrone => {
                  const dx = drone.x - friendlyDrone.x
                  const dy = drone.y - friendlyDrone.y
                  const distance = Math.sqrt(dx * dx + dy * dy)
                  return distance <= FOG_VISIBILITY_RADIUS
                })
              
              // Check if within range of any home base
              const withinBaseRange = Object.values(bases).some(base => {
                const dx = drone.x - base.x
                const dy = drone.y - base.y
                const distance = Math.sqrt(dx * dx + dy * dy)
                return distance <= FOG_VISIBILITY_RADIUS
              })
              
              isVisible = withinFriendlyRange || withinBaseRange
            }
            
            // Don't render enemy drones that are not visible (only when fog of war is enabled)
            if (!isFriendly && !isVisible && fogOfWarEnabled) {
              return null
            }
            
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
                onClick={(e) => handleDroneClick(e, drone.id)}
                onContextMenu={isFriendly ? (e) => handleDroneContextMenu(e, drone) : undefined}
                style={{ cursor: (isFriendly || tailMode) ? 'pointer' : 'default' }}
              >
                {/* Drone shape based on base_shape */}
                {isFriendly && drone.base_shape === 'circle' && (
                  <circle
                    cx={drone.x}
                    cy={drone.y}
                    r={isSelected ? 18 : 16}
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth={isSelected ? 3 : 2}
                    className="drone"
                  />
                )}
                {isFriendly && drone.base_shape === 'square' && (
                  <rect
                    x={drone.x - (isSelected ? 18 : 16)}
                    y={drone.y - (isSelected ? 18 : 16)}
                    width={(isSelected ? 36 : 32)}
                    height={(isSelected ? 36 : 32)}
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth={isSelected ? 3 : 2}
                    className="drone"
                  />
                )}
                {isFriendly && drone.base_shape === 'triangle' && (
                  <polygon
                    points={isSelected 
                      ? `${drone.x},${drone.y - 20} ${drone.x + 18},${drone.y + 14} ${drone.x - 18},${drone.y + 14}`
                      : `${drone.x},${drone.y - 18} ${drone.x + 16},${drone.y + 12} ${drone.x - 16},${drone.y + 12}`
                    }
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth={isSelected ? 3 : 2}
                    className="drone"
                  />
                )}
                {/* Enemy drones stay as circles */}
                {!isFriendly && (
                  <circle
                    cx={drone.x}
                    cy={drone.y}
                    r={isSelected ? 18 : 16}
                    fill={colors.fill}
                    stroke={colors.stroke}
                    strokeWidth={isSelected ? 3 : 2}
                    className="drone"
                  />
                )}
                {/* Drone ID label - centered on circle */}
                <text
                  x={drone.x}
                  y={drone.y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="#ffffff"
                  fontSize="14"
                  fontWeight="bold"
                  pointerEvents="none"
                >
                  {isFriendly ? drone.id.replace('drone_', '') : drone.id.replace('enemy_', '')}
                </text>
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
          
          {/* Fog of War */}
          {fogOfWarEnabled && (
            <>
              <defs>
                <mask id="fogMask">
                  {/* Start with everything white (visible) */}
                  <rect width={worldWidth} height={worldHeight} fill="white"/>
                  
                  {/* Create black circles around friendly drones (fogged areas outside vision) */}
                  {drones
                    .filter(d => d.team === "friendly")
                    .map(drone => (
                      <circle
                        key={`fog-${drone.id}`}
                        cx={drone.x}
                        cy={drone.y}
                        r={FOG_VISIBILITY_RADIUS}
                        fill="black"
                      />
                    ))
                  }
                  {/* Create black circles around home bases (fogged areas outside vision) */}
                  {Object.entries(bases).map(([baseId, base]) => (
                    <circle
                      key={`fog-base-${baseId}`}
                      cx={base.x}
                      cy={base.y}
                      r={FOG_VISIBILITY_RADIUS}
                      fill="black"
                    />
                  ))}
                </mask>
              </defs>
              
              {/* Apply fog overlay - dark semi-transparent layer (mask hides fog in visible areas) */}
              <rect 
                width={worldWidth} 
                height={worldHeight} 
                fill="rgba(0, 0, 0, 0.85)" 
                mask="url(#fogMask)"
                pointerEvents="none"
              />
            </>
          )}
        </svg>
        </div>

        {/* Right: Control Panel (always visible) */}
        <aside className="control-panel">
          <div className="control-panel-header">
            <strong>Control Panel</strong>
          </div>
          
          {/* Selected Drones Section */}
          <div className="selected-drones-section">
            <div className="section-title">Selected Drones:</div>
            <div className="drone-checkboxes">
              {drones.filter(d => d.team === 'friendly').map(drone => (
                <label key={drone.id} className="drone-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedDrones.has(drone.id)}
                    onChange={() => toggleDroneSelection(drone.id)}
                  />
                  <span className="drone-number">{drone.id.replace('drone_', '')}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Commands Section */}
          <div className="commands-section">
            <div className="section-title">Commands:</div>
            
            <div className="action-item" onClick={stopSelectedDrones} role="button" tabIndex={0}>
              <svg width="20" height="20" viewBox="0 0 24 24" className="command-icon" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L2 7v10c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-10-5z" fill="none" stroke="#888" strokeWidth="1.5"/>
                <rect x="7" y="10" width="10" height="4" fill="#888"/>
              </svg>
              <span>Stop</span>
            </div>

            <div className="action-item" onClick={startPatrolMode} role="button" tabIndex={0}>
              <svg width="20" height="20" viewBox="0 0 24 24" className="command-icon" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L4 8v8l8 6 8-6V8l-8-6z" fill="none" stroke="#888" strokeWidth="1.5"/>
                <polyline points="12,8 16,12 12,16 8,12 12,8" fill="none" stroke="#888" strokeWidth="1.5"/>
                <circle cx="12" cy="12" r="2" fill="#888"/>
                <line x1="12" y1="2" x2="12" y2="8" stroke="#888" strokeWidth="1.5"/>
                <line x1="12" y1="16" x2="12" y2="22" stroke="#888" strokeWidth="1.5"/>
              </svg>
              <span>Patrol</span>
            </div>

            <div className="action-item" onClick={startTailMode} role="button" tabIndex={0}>
              <svg width="20" height="20" viewBox="0 0 24 24" className="command-icon" xmlns="http://www.w3.org/2000/svg">
                <circle cx="12" cy="12" r="9" fill="none" stroke="#888" strokeWidth="1.5"/>
                <circle cx="12" cy="12" r="3" fill="#888"/>
                <line x1="12" y1="12" x2="18" y2="6" stroke="#888" strokeWidth="1.5"/>
                <circle cx="18" cy="6" r="2" fill="none" stroke="#888" strokeWidth="1.5"/>
                <path d="M 17 5 L 19 5 L 18 3 Z" fill="#888"/>
              </svg>
              <span>Tail Enemy</span>
            </div>

            <div className="action-item" onClick={returnToBase} role="button" tabIndex={0}>
              <svg width="20" height="20" viewBox="0 0 24 24" className="command-icon" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z" fill="#888" stroke="#888" strokeWidth="1"/>
                <path d="M12 3L12 8" stroke="#888" strokeWidth="2"/>
                <circle cx="12" cy="2" r="1.5" fill="#00ff88"/>
              </svg>
              <span>Return to Base</span>
            </div>
          </div>

          {/* Base Selection Section */}
          <div className="base-selection-section">
            <div className="section-title">Change Home Base:</div>
            <div className="base-buttons">
              {Object.entries(bases).map(([baseId, base]) => (
                <div 
                  key={baseId} 
                  className="base-button" 
                  onClick={() => setDroneBase(baseId)}
                  role="button" 
                  tabIndex={0}
                >
                  <svg width="30" height="30" viewBox="0 0 40 40" className="base-icon">
                    {base.shape === 'circle' && (
                      <circle cx="20" cy="20" r="15" fill="none" stroke="#00ff88" strokeWidth="2"/>
                    )}
                    {base.shape === 'square' && (
                      <rect x="5" y="5" width="30" height="30" fill="none" stroke="#00ff88" strokeWidth="2"/>
                    )}
                    {base.shape === 'triangle' && (
                      <polygon points="20,5 35,35 5,35" fill="none" stroke="#00ff88" strokeWidth="2"/>
                    )}
                  </svg>
                  <span className="base-name">{base.name}</span>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>

      {/* Bottom: Instructions */}
      <div className="bottom-bar">
        <div className="instructions">
          {patrolMode ? (
            <p style={{ color: '#00ff88', fontWeight: 'bold' }}>🎯 PATROL MODE: Click on map to set patrol target point</p>
          ) : tailMode ? (
            <p style={{ color: '#ff4444', fontWeight: 'bold' }}>👁️ TAIL MODE: Click on an enemy drone to tail</p>
          ) : (
            <p>Click drone to select • Drag box to select multiple • Click map to move selected drones • Use Commands panel or Control panel to issue orders • ESC to deselect</p>
          )}
        </div>
      </div>
      
      {/* Task Menu Dropdown */}
      {showTaskMenu && taskMenuDrone && (
        <div 
          className="task-menu"
          style={{
            position: 'fixed',
            left: taskMenuPosition.x,
            top: taskMenuPosition.y,
            zIndex: 1000
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="task-menu-header">
            <h3>Task Menu - {taskMenuDrone.id}</h3>
            <button onClick={() => setShowTaskMenu(false)}>×</button>
          </div>
          <div className="task-menu-content">
            <label>
              Select Task:
              <select 
                value={selectedTask} 
                onChange={(e) => {
                  setSelectedTask(e.target.value)
                  setTaskParams({})
                }}
              >
                <option value="">-- Select Task --</option>
                {Object.entries(availableTasks).map(([name, task]) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
            
            {selectedTask === "tail" && (
              <div className="task-params">
                <label>
                  Enemy Drone:
                  <select 
                    value={taskParams.enemy_drone || ""}
                    onChange={(e) => setTaskParams({...taskParams, enemy_drone: e.target.value})}
                  >
                    <option value="">-- Select Enemy --</option>
                    {drones.filter(d => d.team === "enemy").map(d => (
                      <option key={d.id} value={d.id}>{d.id}</option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            
            {selectedTask === "patrol" && (
              <div className="task-params">
                <p>Click on map to set patrol points (coming soon)</p>
              </div>
            )}
            
            <button 
              onClick={handleExecuteTask}
              disabled={!selectedTask}
              className="execute-button"
            >
              Execute
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App

