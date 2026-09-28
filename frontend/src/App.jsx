import { useState, useEffect, useRef, useCallback } from 'react';
import './index.css';

export default function App() {
  const [state, setState] = useState('IDLE');
  const [statusMessage, setStatusMessage] = useState('Initializing...');
  const [history, setHistory] = useState([]);
  const [isConnected, setIsConnected] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [micLevel, setMicLevel] = useState(0);

  const wsRef = useRef(null);
  const logEndRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const micAnimationRef = useRef(null);

  const stateConfig = {
    IDLE: { label: 'JARVIS', color: '#00e5ff', pulse: true },
    LISTENING_FOR_WAKE_WORD: { label: 'LISTENING', color: '#00e5ff', pulse: true },
    LISTENING_FOR_COMMAND: { label: 'LISTENING', color: '#22d3ee', pulse: false },
    THINKING: { label: 'THINKING', color: '#fbbf24', pulse: true },
    EXECUTING: { label: 'EXECUTING', color: '#f97316', pulse: false },
    SPEAKING: { label: 'SPEAKING', color: '#22c55e', pulse: false },
    ERROR: { label: 'ERROR', color: '#ef4444', pulse: false },
  };

  const getStateConfig = useCallback((s) => stateConfig[s] || stateConfig.IDLE, []);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [history]);

  useEffect(() => {
    const config = getStateConfig(state);
    if (config.pulse && (state === 'LISTENING_FOR_COMMAND' || state === 'LISTENING_FOR_WAKE_WORD')) {
      micAnimationRef.current = requestAnimationFrame(animateMic);
    } else {
      if (micAnimationRef.current) cancelAnimationFrame(micAnimationRef.current);
      setMicLevel(0);
    }
    return () => {
      if (micAnimationRef.current) cancelAnimationFrame(micAnimationRef.current);
    };
  }, [state]);

  const animateMic = () => {
    if (micAnimationRef.current) {
      setMicLevel(prev => Math.min(100, prev + Math.random() * 20));
      setTimeout(() => setMicLevel(prev => Math.max(0, prev - Math.random() * 15)), 50);
      micAnimationRef.current = requestAnimationFrame(animateMic);
    }
  };

  const connectWs = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    
    const wsUrl = `ws://${window.location.hostname}:8000/ws/events`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      setStatusMessage('System Online · Listening for wake word...');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'state_change') {
          setState(data.state);
          if (data.message) setStatusMessage(data.message);
        } else if (data.type === 'transcription') {
          setHistory(prev => {
            const last = prev[prev.length - 1];
            if (last && last.text === data.text) return prev;
            return [...prev, { 
              id: Date.now() + Math.random(), 
              time: new Date().toLocaleTimeString(), 
              text: data.text,
              type: data.text.startsWith('JARVIS:') ? 'assistant' : 'user'
            }];
          });
        }
      } catch (e) {
        console.error('WS Parse error', e);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      setStatusMessage('Connection lost. Reconnecting...');
      setState('ERROR');
      reconnectTimerRef.current = setTimeout(connectWs, 3000);
    };

    ws.onerror = () => {
      setIsConnected(false);
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    connectWs();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connectWs]);

  const handleManualTrigger = async () => {
    setStatusMessage('Activating microphone...');
    try {
      const res = await fetch(`http://${window.location.hostname}:8000/voice/listen`, { method: 'POST' });
      const data = await res.json();
      setStatusMessage(data.started ? 'Listening... speak now.' : data.detail);
    } catch (e) {
      setStatusMessage('Backend not reachable.');
    }
  };

  const clearHistory = () => setHistory([]);
  const toggleSettings = () => setShowSettings(!showSettings);

  const config = getStateConfig(state);
  const isActive = ['LISTENING_FOR_COMMAND', 'LISTENING_FOR_WAKE_WORD', 'THINKING', 'EXECUTING', 'SPEAKING'].includes(state);

  return (
    <div className="jarvis-app">
      {/* Background Effects */}
      <div className={`bg-grid ${isActive ? 'active' : ''}`} />
      <div className={`orb orb-1 ${state === 'SPEAKING' ? 'speaking' : ''}`} />
      <div className={`orb orb-2 ${state === 'THINKING' ? 'thinking' : ''}`} />
      <div className={`orb orb-3 ${state === 'LISTENING_FOR_COMMAND' ? 'listening' : ''}`} />

      {/* Top Bar */}
      <header className="top-bar">
        <div className="brand">
          <div className="logo">
            <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="16" cy="16" r="14" stroke="currentColor" strokeWidth="2"/>
              <path d="M16 6V10M16 22V26M6 16H10M22 16H26" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </div>
          <div>
            <h1>JARVIS</h1>
            <span className="version">v4.2.0</span>
          </div>
        </div>
        
        <div className="status-indicators">
          <div className={`status-dot ${isConnected ? 'connected' : 'disconnected'}`}>
            <span className="dot"></span>
            <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
          </div>
          <div className={`status-dot ${config.pulse ? 'active' : ''} mic-indicator`}>
            <span className="dot"></span>
            <span className="mic-level" style={{width: `${micLevel}%`}}></span>
            <span>{getStateConfig(state).label}</span>
          </div>
        </div>
        
        <button className="icon-btn" onClick={toggleSettings} aria-label="Settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 1 4.6 9a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V15a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09a1.65 1.65 0 0 1 1.51-1H3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 1-1.51 1z"/>
          </svg>
        </button>
      </header>

      <main className="main-content">
        {/* Left Panel - Conversation */}
        <aside className="panel conversation-panel">
          <div className="panel-header">
            <h2>Conversation</h2>
            <button className="icon-btn clear-btn" onClick={() => setHistory([])} aria-label="Clear history">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
          </div>
          <div className="conversation-list" ref={logEndRef}>
            {history.length === 0 ? (
              <div className="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5l-4 4z"/>
                </svg>
                <p>No conversation yet</p>
                <span>Say "Hey Jarvis" or click Listen</span>
              </div>
            ) : (
              history.map((log, i) => (
                <div key={log.id} className={`message ${log.type}`}>
                  <div className="message-header">
                    <span className="role">{log.type === 'user' ? 'YOU' : 'JARVIS'}</span>
                    <span className="time">{log.time}</span>
                  </div>
                  <div className="message-text">{log.text}</div>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </aside>

        {/* Center - Voice Visualizer */}
        <section className="center-panel">
          <div className="voice-visualizer">
            <div className={`visualizer-ring outer ${state === 'LISTENING_FOR_COMMAND' ? 'active' : ''}`}></div>
            <div className={`visualizer-ring middle ${state === 'THINKING' ? 'active' : ''}`}></div>
            <div className={`visualizer-ring inner ${state === 'SPEAKING' ? 'active' : ''}`}></div>
            <div className={`core ${state === 'SPEAKING' ? 'speaking' : ''} ${state === 'THINKING' ? 'thinking' : ''}`}>
              <span className="core-text">JARVIS</span>
              <div className="waveform" aria-hidden="true">
                {[...Array(20)].map((_, i) => (
                  <div key={i} className="bar" style={{animationDelay: `${i * 50}ms`}} />
                ))}
              </div>
            </div>
          </div>

          <div className="status-display">
            <h2 className="state-label">{getStateConfig(state).label}</h2>
            <p className="status-text">{statusMessage}</p>
          </div>

          <button 
            className={`listen-btn ${state === 'LISTENING_FOR_COMMAND' ? 'active' : ''}`}
            onClick={handleManualTrigger}
            disabled={state === 'LISTENING_FOR_COMMAND'}
            aria-label="Start listening"
          >
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c.3-.4.5-1 .5-1.5 0-.55-.45-1-1-1H8c-.55 0-1 .45-1 1 0 .5.2 1.1.5 1.5.3.4.6.9.7 1.4.3 1.1.9 2 1.9 2.3s1.8.2 2.5 0c.7-.3 1.2-.9 1.5-1.9.2-.5.2-1 .2-1.5 0-.55-.45-1-1-1H8c-.55 0-1 .45-1 1 0 .5.2 1.1.5 1.5.3.4.6.9.7 1.4.3 1.1.9 2 1.9 2.3s1.8.2 2.5 0c.7-.3 1.2-.9 1.5-1.9.2-.5.2-1 .2-1.5 0-.55-.45-1-1-1h-.5c-.55 0-1-.45-1-1V7c0-.55.45-1 1-1h10c.55 0 1 .45 1 1v1h.5c.55 0 1 .45 1 1 0 .5-.2 1-.5 1.5z"/>
            </svg>
            <span>{state === 'LISTENING_FOR_COMMAND' ? 'Listening...' : 'Listen'}</span>
            <div className="btn-ring"></div>
          </button>
        </section>

        {/* Right Panel - System & Tools */}
        <aside className="panel system-panel">
          <div className="panel-header">
            <h2>System</h2>
            <span className={`status-badge ${isConnected ? 'online' : 'offline'}`}>
              {isConnected ? 'Online' : 'Offline'}
            </span>
          </div>
          
          <div className="system-grid">
            <div className="sys-card">
              <div className="sys-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="2" y="3" width="20" height="14" rx="2"></rect>
                  <path d="M8 21h8M12 17v4"></path>
                </svg>
              </div>
              <div className="sys-info">
                <span className="sys-label">CPU</span>
                <span className="sys-value">24%</span>
              </div>
            </div>
            <div className="sys-card">
              <div className="sys-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 22V12M12 2V10"></path>
                  <path d="M4 10H20M4 14H20M4 18H20"></path>
                </svg>
              </div>
              <div className="sys-info">
                <span className="sys-label">Memory</span>
                <span className="sys-value">42%</span>
              </div>
            </div>
            <div className="sys-card">
              <div className="sys-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"></circle>
                  <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
              </div>
              <div className="sys-info">
                <span className="sys-label">Uptime</span>
                <span className="sys-value">2h 34m</span>
              </div>
            </div>
          </div>

          <div className="tools-section">
            <h3>Quick Tools</h3>
            <div className="tool-grid">
              {[
                { name: 'Web Search', icon: 'search', tool: 'web_search' },
                { name: 'Open Project', icon: 'folder', tool: 'list_projects' },
                { name: 'Terminal', icon: 'terminal', tool: 'run_dev_command' },
                { name: 'Screenshot', icon: 'camera', tool: 'take_screenshot' },
              ].map(t => (
                <button key={t.name} className="tool-btn" onClick={() => console.log(t.tool)}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    {t.icon === 'search' && (
                      <>
                        <circle cx="11" cy="11" r="8"></circle>
                        <path d="M21 21l-4.35-4.35"></path>
                      </>
                    )}
                    {t.icon === 'folder' && (
                      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                    )}
                    {t.icon === 'terminal' && (
                      <>
                        <polyline points="4 17 10 11 4 5"></polyline>
                        <line x1="12" y1="19" x2="20" y2="19"></line>
                      </>
                    )}
                    {t.icon === 'camera' && (
                      <>
                        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                        <circle cx="12" cy="12" r="4"></circle>
                      </>
                    )}
                  </svg>
                  <span>{t.name}</span>
                </button>
              ))}
            </div>
          </div>
        </aside>
      </main>

      {/* Settings Modal */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Settings</h2>
              <button className="icon-btn" onClick={() => setShowSettings(false)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
            <div className="modal-body">
              <div className="setting-group">
                <label>Wake Word Threshold</label>
                <input type="range" min="0" max="1" step="0.01" defaultValue={0.5} />
              </div>
              <div className="setting-group">
                <label>Response Language</label>
                <select defaultValue="auto">
                  <option value="auto">Auto Detect</option>
                  <option value="English">English</option>
                  <option value="Hindi">Hindi</option>
                  <option value="Marathi">Marathi</option>
                </select>
              </div>
              <div className="setting-group">
                <label>TTS Provider</label>
                <select defaultValue="sarvam">
                  <option value="sarvam">Sarvam</option>
                  <option value="edge">Edge TTS</option>
                </select>
              </div>
              <div className="setting-group">
                <label>Barge-in (Interrupt)</label>
                <input type="checkbox" defaultChecked={false} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn primary" onClick={() => setShowSettings(false)}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}